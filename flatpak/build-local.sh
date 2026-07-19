#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="$(cd "$SCRIPT_DIR/.." && pwd)"
APP_ID="io.github.zuraffpl.Sesyjka"
MANIFEST="$SCRIPT_DIR/$APP_ID.yml"
BUILD_DIR="${1:-$SOURCE_DIR/.flatpak-build}"

if command -v flatpak-builder >/dev/null 2>&1; then
  flatpak-builder --user --install --force-clean "$BUILD_DIR" "$MANIFEST"
elif flatpak info org.flatpak.Builder >/dev/null 2>&1; then
  flatpak run org.flatpak.Builder --user --install --force-clean "$BUILD_DIR" "$MANIFEST"
else
  cat >&2 <<'TXT'
Brak Flatpak Builder.

Zainstaluj narzędzie i środowiska wykonawcze:
  flatpak install --user flathub org.flatpak.Builder org.gnome.Platform//50 org.gnome.Sdk//50
TXT
  exit 1
fi

echo "Zainstalowano lokalny pakiet Flatpak: $APP_ID"
echo "Uruchomienie: flatpak run $APP_ID"
