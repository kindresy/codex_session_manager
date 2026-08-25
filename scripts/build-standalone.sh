#!/bin/sh
set -eu

ROOT=$(CDPATH= cd -- "$(dirname "$0")/.." && pwd -P)
cd "$ROOT"
ARCHIVE=codex-session-manager-linux-x86_64.tar.gz

PYTHONPATH=src python -m unittest discover -s tests -v
rm -rf build/standalone dist/standalone dist/release
mkdir -p build/standalone dist/standalone dist/release
python -m PyInstaller --clean --noconfirm \
    --workpath build/standalone \
    --distpath dist/standalone \
    packaging/codex-session.spec
cp README.md LICENSE dist/standalone/codex-session-manager/

dist/standalone/codex-session-manager/codex-session --help >/dev/null
dist/standalone/codex-session-manager/codex-session --version
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-0}
export SOURCE_DATE_EPOCH
tar --sort=name --owner=0 --group=0 --numeric-owner \
    --mtime="@$SOURCE_DATE_EPOCH" \
    -C dist/standalone -czf "dist/release/$ARCHIVE" codex-session-manager
(cd dist/release && sha256sum "$ARCHIVE" >"$ARCHIVE.sha256")
cp scripts/install.sh dist/release/install.sh
python tests/verify_standalone.py "dist/release/$ARCHIVE" "$ROOT"
