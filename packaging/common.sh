#!/usr/bin/env bash
set -euo pipefail

PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
APP_ID="io.github.zuraffpl.Sesyjka"
UPDATE_REPOSITORY="Lioheart/Sesyjka"

project_version() {
  python3 - "$PROJECT_ROOT/pyproject.toml" <<'PY'
from pathlib import Path
import re
import sys
text = Path(sys.argv[1]).read_text(encoding="utf-8")
match = re.search(r'^version\s*=\s*"([0-9]+\.[0-9]+\.[0-9]+)"\s*$', text, re.MULTILINE)
if not match:
    raise SystemExit("Nie znaleziono wersji w pyproject.toml")
print(match.group(1))
PY
}

validate_version() {
  local requested="${1:-$(project_version)}"
  local project
  project="$(project_version)"
  if [[ "$requested" != "$project" ]]; then
    echo "Wersja $requested nie jest zgodna z pyproject.toml ($project)." >&2
    exit 2
  fi
  printf '%s\n' "$requested"
}

stage_system_files() {
  local root="$1"
  local channel="$2"
  local app_root="${3:-/usr/share/sesyjka}"
  local bin_path="${4:-/usr/bin/sesyjka}"
  local data_prefix="${5:-/usr/share}"

  rm -rf "$root"
  install -d \
    "$root$app_root" \
    "$root$(dirname "$bin_path")" \
    "$root$data_prefix/applications" \
    "$root$data_prefix/metainfo" \
    "$root$data_prefix/doc/sesyjka"

  cp -a "$PROJECT_ROOT/sesyjka" "$root$app_root/"
  cp -a "$PROJECT_ROOT/data" "$root$app_root/"
  find "$root$app_root" -type d -name __pycache__ -prune -exec rm -rf {} +
  find "$root$app_root" -type f \( -name '*.pyc' -o -name '*.pyo' \) -delete
  install -m 0644 "$PROJECT_ROOT/LICENSE" "$root$data_prefix/doc/sesyjka/LICENSE"
  install -m 0644 "$PROJECT_ROOT/NOTICE.md" "$root$data_prefix/doc/sesyjka/NOTICE.md"
  install -m 0644 "$PROJECT_ROOT/README.md" "$root$data_prefix/doc/sesyjka/README.md"
  if [[ -f "$PROJECT_ROOT/README.en.md" ]]; then
    install -m 0644 "$PROJECT_ROOT/README.en.md" "$root$data_prefix/doc/sesyjka/README.en.md"
  fi

  cat > "$root$bin_path" <<WRAPPER
#!/usr/bin/env sh
export SESYJKA_INSTALL_CHANNEL="$channel"
export SESYJKA_UPDATE_REPOSITORY="$UPDATE_REPOSITORY"
PYTHONPATH="$app_root\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m sesyjka "\$@"
WRAPPER
  chmod 0755 "$root$bin_path"

  sed "s|^Exec=.*$|Exec=$bin_path|" \
    "$PROJECT_ROOT/data/$APP_ID.desktop" \
    > "$root$data_prefix/applications/$APP_ID.desktop"
  chmod 0644 "$root$data_prefix/applications/$APP_ID.desktop"
  install -m 0644 \
    "$PROJECT_ROOT/data/$APP_ID.metainfo.xml" \
    "$root$data_prefix/metainfo/$APP_ID.metainfo.xml"

  while IFS= read -r -d '' icon; do
    local relative destination
    relative="${icon#"$PROJECT_ROOT/data/icons/hicolor/"}"
    destination="$root$data_prefix/icons/hicolor/$(dirname "$relative")"
    install -d "$destination"
    install -m 0644 "$icon" "$destination/"
  done < <(find "$PROJECT_ROOT/data/icons/hicolor" -type f \
    \( -name "$APP_ID.svg" -o -name "$APP_ID.png" \) -print0)
}
