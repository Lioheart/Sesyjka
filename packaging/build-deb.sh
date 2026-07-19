#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

VERSION="$(validate_version "${1:-}")"
OUTPUT_DIR="${2:-$PROJECT_ROOT/dist}"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
BUILD_DIR="$(mktemp -d)"
trap 'rm -rf "$BUILD_DIR"' EXIT
ROOT="$BUILD_DIR/root"

if ! command -v dpkg-deb >/dev/null 2>&1; then
  echo "Brak dpkg-deb. Zainstaluj pakiet dpkg-dev." >&2
  exit 1
fi

stage_system_files "$ROOT" "deb"
install -d "$ROOT/DEBIAN"
cat > "$ROOT/DEBIAN/control" <<CONTROL
Package: sesyjka
Version: $VERSION
Section: games
Priority: optional
Architecture: all
Maintainer: Lioheart <noreply@github.com>
Depends: python3 (>= 3.10), python3-gi, gir1.2-gtk-4.0, gir1.2-adw-1, python3-openpyxl, pkexec
Homepage: https://github.com/Lioheart/Sesyjka
Description: GTK4 application for tabletop RPG collections and sessions
 Sesyjka manages RPG systems, books, supplements, sessions, players,
 publishers, statistics and compatible SQLite databases.
CONTROL

cat > "$ROOT/DEBIAN/postinst" <<'POSTINST'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
command -v gtk4-update-icon-cache >/dev/null 2>&1 && gtk4-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
exit 0
POSTINST
cat > "$ROOT/DEBIAN/postrm" <<'POSTRM'
#!/bin/sh
set -e
command -v update-desktop-database >/dev/null 2>&1 && update-desktop-database /usr/share/applications >/dev/null 2>&1 || true
command -v gtk4-update-icon-cache >/dev/null 2>&1 && gtk4-update-icon-cache -f /usr/share/icons/hicolor >/dev/null 2>&1 || true
exit 0
POSTRM
chmod 0755 "$ROOT/DEBIAN/postinst" "$ROOT/DEBIAN/postrm"

TARGET="$OUTPUT_DIR/sesyjka_${VERSION}_all.deb"
dpkg-deb --root-owner-group --build "$ROOT" "$TARGET"
printf '%s\n' "$TARGET"
