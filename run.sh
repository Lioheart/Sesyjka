#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Wyłącznie uruchamia kod z bieżącego katalogu. Nie instaluje ani nie aktualizuje plików.
export SESYJKA_INSTALL_CHANNEL="${SESYJKA_INSTALL_CHANNEL:-local}"
export SESYJKA_UPDATE_REPOSITORY="${SESYJKA_UPDATE_REPOSITORY:-Lioheart/Sesyjka}"
PYTHON="${SESYJKA_PYTHON:-python3}"
exec "$PYTHON" -m sesyjka "$@"
