#!/usr/bin/env bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
# shellcheck source=common.sh
source "$SCRIPT_DIR/common.sh"

VERSION="$(validate_version "${1:-}")"
OUTPUT_DIR="${2:-$PROJECT_ROOT/dist}"
mkdir -p "$OUTPUT_DIR"
OUTPUT_DIR="$(cd "$OUTPUT_DIR" && pwd)"
TOPDIR="$(mktemp -d)"
STAGE="$(mktemp -d)"
trap 'rm -rf "$TOPDIR" "$STAGE"' EXIT

if ! command -v rpmbuild >/dev/null 2>&1; then
  echo "Brak rpmbuild. Zainstaluj pakiet rpm-build." >&2
  exit 1
fi

mkdir -p "$TOPDIR"/{BUILD,BUILDROOT,RPMS,SOURCES,SPECS,SRPMS}
SOURCE_ROOT="$STAGE/sesyjka-$VERSION"
mkdir -p "$SOURCE_ROOT"
stage_release_source "$SOURCE_ROOT"
(
  cd "$STAGE"
  tar --sort=name --owner=0 --group=0 --numeric-owner -czf \
    "$TOPDIR/SOURCES/sesyjka-$VERSION.tar.gz" "sesyjka-$VERSION"
)
sed "s/@VERSION@/$VERSION/g" "$SCRIPT_DIR/rpm/sesyjka.spec.in" \
  > "$TOPDIR/SPECS/sesyjka.spec"

rpmbuild --define "_topdir $TOPDIR" -bb "$TOPDIR/SPECS/sesyjka.spec"
find "$TOPDIR/RPMS" -type f -name '*.rpm' -exec cp -a {} "$OUTPUT_DIR/" \;
find "$OUTPUT_DIR" -maxdepth 1 -type f -name "sesyjka-$VERSION-*.noarch.rpm" -print
