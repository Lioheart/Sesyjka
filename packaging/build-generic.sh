#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

VERSION="$(validate_version "${1:-}")"
OUTPUT_DIR="${2:-$PROJECT_ROOT/dist}"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
PACKAGE_ROOT="$STAGE/sesyjka-$VERSION"
mkdir -p "$PACKAGE_ROOT"
stage_release_source "$PACKAGE_ROOT"

TAR_NAME="sesyjka-$VERSION-linux-installer.tar.gz"
ZIP_NAME="sesyjka-$VERSION-linux-installer.zip"
(
  cd "$STAGE"
  tar --sort=name --owner=0 --group=0 --numeric-owner -czf "$OUTPUT_DIR/$TAR_NAME" "sesyjka-$VERSION"
  python3 - "$OUTPUT_DIR/$ZIP_NAME" "sesyjka-$VERSION" <<'PY'
from pathlib import Path
import sys
import zipfile
out = Path(sys.argv[1])
root = Path(sys.argv[2])
with zipfile.ZipFile(out, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
    for path in sorted(root.rglob("*")):
        if path.is_file():
            info = zipfile.ZipInfo.from_file(path, path.as_posix())
            info.create_system = 3
            with path.open("rb") as handle:
                archive.writestr(info, handle.read(), compress_type=zipfile.ZIP_DEFLATED, compresslevel=9)
PY
)
printf '%s\n%s\n' "$OUTPUT_DIR/$TAR_NAME" "$OUTPUT_DIR/$ZIP_NAME"
