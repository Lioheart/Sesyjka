#!/usr/bin/env bash
set -euo pipefail

APP_ID="io.github.zuraffpl.Sesyjka"
INSTALL_ROOT="${SESYJKA_INSTALL_ROOT:-/opt/sesyjka}"
BIN_PATH="${SESYJKA_BIN_PATH:-/usr/local/bin/sesyjka}"
DATA_PREFIX="${SESYJKA_SYSTEM_DATA_PREFIX:-/usr/local/share}"
PURGE_DATA=false
ASSUME_YES=false

while (($#)); do
  case "$1" in
    --purge-data) PURGE_DATA=true ;;
    -y|--yes) ASSUME_YES=true ;;
    -h|--help)
      cat <<'TXT'
Użycie:
  ./uninstall-linux.sh
      usuwa systemową instalację z /opt i /usr/local

  ./uninstall-linux.sh --purge-data
      dodatkowo usuwa dane i ustawienia bieżącego użytkownika

  ./uninstall-linux.sh --purge-data --yes
      usuwa dane bez pytania o potwierdzenie

Deinstalator nie usuwa danych innych użytkowników systemu ani danych Flatpaka.
TXT
      exit 0
      ;;
    *)
      echo "Nieznana opcja: $1" >&2
      exit 2
      ;;
  esac
  shift
done

if [[ "${EUID}" -eq 0 ]]; then
  SUDO=()
else
  if ! command -v sudo >/dev/null 2>&1; then
    echo "Usunięcie instalacji systemowej wymaga polecenia sudo." >&2
    exit 1
  fi
  SUDO=(sudo)
fi

APPLICATION_PATH="$DATA_PREFIX/applications/$APP_ID.desktop"
METAINFO_PATH="$DATA_PREFIX/metainfo/$APP_ID.metainfo.xml"
ICON_ROOT="$DATA_PREFIX/icons/hicolor"

"${SUDO[@]}" rm -rf "$INSTALL_ROOT"
"${SUDO[@]}" rm -f "$BIN_PATH" "$APPLICATION_PATH" "$METAINFO_PATH"
while IFS= read -r -d '' icon; do
  "${SUDO[@]}" rm -f "$icon"
done < <(find "$ICON_ROOT" -type f \
  \( -path "*/apps/$APP_ID.svg" -o -path "*/apps/$APP_ID.png" \) -print0 2>/dev/null || true)

if command -v update-desktop-database >/dev/null 2>&1; then
  "${SUDO[@]}" update-desktop-database "$DATA_PREFIX/applications" >/dev/null 2>&1 || true
fi
if command -v gtk4-update-icon-cache >/dev/null 2>&1; then
  "${SUDO[@]}" gtk4-update-icon-cache -f "$ICON_ROOT" >/dev/null 2>&1 || true
fi

effective_home="$HOME"
if [[ "${EUID}" -eq 0 && -n "${SUDO_USER:-}" && "${SUDO_USER}" != "root" ]]; then
  user_home="$(getent passwd "$SUDO_USER" | cut -d: -f6 || true)"
  [[ -n "$user_home" ]] && effective_home="$user_home"
fi
DATA_DIR="${SESYJKA_DATA_DIR:-${XDG_DATA_HOME:-$effective_home/.local/share}/sesyjka}"
CONFIG_DIR="${SESYJKA_CONFIG_DIR:-${XDG_CONFIG_HOME:-$effective_home/.config}/sesyjka}"

if $PURGE_DATA; then
  answer=""
  if $ASSUME_YES; then
    answer="yes"
  else
    printf 'Usunąć dane bieżącego użytkownika z:\n  %s\n  %s\n? [y/N] ' \
      "$DATA_DIR" "$CONFIG_DIR"
    read -r answer
  fi
  case "$answer" in
    y|Y|yes|YES|tak|TAK)
      rm -rf "$DATA_DIR" "$CONFIG_DIR"
      echo "Usunięto instalację systemową, dane i ustawienia bieżącego użytkownika."
      ;;
    *)
      echo "Usunięto instalację systemową. Dane użytkownika pozostawiono."
      ;;
  esac
else
  echo "Usunięto instalację systemową Sesyjki."
  echo "Dane użytkownika pozostawiono w: $DATA_DIR"
  echo "Ustawienia pozostawiono w: $CONFIG_DIR"
fi
