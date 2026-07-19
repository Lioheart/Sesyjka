#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
APP_ID="io.github.zuraffpl.Sesyjka"
UPDATE_REPOSITORY="Lioheart/Sesyjka"
INSTALL_ROOT="${SESYJKA_INSTALL_ROOT:-/opt/sesyjka}"
BIN_PATH="${SESYJKA_BIN_PATH:-/usr/local/bin/sesyjka}"
DATA_PREFIX="${SESYJKA_SYSTEM_DATA_PREFIX:-/usr/local/share}"
APPLICATION_PATH="$DATA_PREFIX/applications/$APP_ID.desktop"
METAINFO_PATH="$DATA_PREFIX/metainfo/$APP_ID.metainfo.xml"
ICON_ROOT="$DATA_PREFIX/icons/hicolor"

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Instalacja systemowa wymaga uprawnień administratora i polecenia sudo." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

check_dependencies() {
  if [[ "${SESYJKA_SKIP_DEPENDENCY_CHECK:-0}" == "1" ]]; then
    return
  fi
  if ! python3 - <<'PY'
import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Adw, Gtk  # noqa: F401
import openpyxl  # noqa: F401
PY
  then
    cat >&2 <<'TXT'
Brakuje zależności systemowych.

Debian lub Ubuntu:
  sudo apt install python3 python3-gi gir1.2-gtk-4.0 gir1.2-adw-1 python3-openpyxl

Fedora:
  sudo dnf install python3 python3-gobject gtk4 libadwaita python3-openpyxl

Arch Linux:
  sudo pacman -S python python-gobject gtk4 libadwaita python-openpyxl
TXT
    exit 1
  fi
}

check_dependencies

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
mkdir -p "$STAGE/app" "$STAGE/bin"
cp -a "$SCRIPT_DIR/sesyjka" "$STAGE/app/"
cp -a "$SCRIPT_DIR/data" "$STAGE/app/"
cp -a "$SCRIPT_DIR/LICENSE" "$SCRIPT_DIR/NOTICE.md" "$SCRIPT_DIR/README.md" "$STAGE/app/"
cp -a "$SCRIPT_DIR/uninstall-linux.sh" "$STAGE/app/"
chmod 0755 "$STAGE/app/uninstall-linux.sh"

cat > "$STAGE/bin/sesyjka" <<WRAPPER
#!/usr/bin/env sh
export SESYJKA_INSTALL_CHANNEL="generic"
export SESYJKA_UPDATE_REPOSITORY="$UPDATE_REPOSITORY"
PYTHONPATH="$INSTALL_ROOT\${PYTHONPATH:+:\$PYTHONPATH}" exec python3 -m sesyjka "\$@"
WRAPPER
chmod 0755 "$STAGE/bin/sesyjka"

DESKTOP_STAGE="$STAGE/$APP_ID.desktop"
sed "s|^Exec=.*$|Exec=$BIN_PATH|" \
  "$SCRIPT_DIR/data/$APP_ID.desktop" > "$DESKTOP_STAGE"

"${SUDO[@]}" rm -rf "$INSTALL_ROOT"
"${SUDO[@]}" install -d -m 0755 \
  "$INSTALL_ROOT" \
  "$(dirname "$BIN_PATH")" \
  "$(dirname "$APPLICATION_PATH")" \
  "$(dirname "$METAINFO_PATH")"
"${SUDO[@]}" cp -a "$STAGE/app/." "$INSTALL_ROOT/"
"${SUDO[@]}" install -m 0755 "$STAGE/bin/sesyjka" "$BIN_PATH"
"${SUDO[@]}" install -m 0644 "$DESKTOP_STAGE" "$APPLICATION_PATH"
"${SUDO[@]}" install -m 0644 \
  "$SCRIPT_DIR/data/$APP_ID.metainfo.xml" "$METAINFO_PATH"

while IFS= read -r -d '' icon; do
  relative="${icon#"$SCRIPT_DIR/data/icons/hicolor/"}"
  destination="$ICON_ROOT/$(dirname "$relative")"
  "${SUDO[@]}" install -d -m 0755 "$destination"
  "${SUDO[@]}" install -m 0644 "$icon" "$destination/"
done < <(find "$SCRIPT_DIR/data/icons/hicolor" -type f \
  \( -name "$APP_ID.svg" -o -name "$APP_ID.png" \) -print0)

if command -v update-desktop-database >/dev/null 2>&1; then
  "${SUDO[@]}" update-desktop-database "$DATA_PREFIX/applications" >/dev/null 2>&1 || true
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  "${SUDO[@]}" gtk4-update-icon-cache -f "$ICON_ROOT" >/dev/null 2>&1 || true
fi

cat <<TXT
Zainstalowano Sesyjkę systemowo.
Program: $BIN_PATH
Pliki aplikacji: $INSTALL_ROOT
Odinstalowanie: $INSTALL_ROOT/uninstall-linux.sh
TXT
