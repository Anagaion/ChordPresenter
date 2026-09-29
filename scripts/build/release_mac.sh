#!/usr/bin/env bash
# Build the universal (Apple Silicon + Intel) ChordPresenter .dmg with Python
# bundled inside, so users need nothing else installed.
#
#   scripts/build/release_mac.sh
#
# Output: src-tauri/target/universal-apple-darwin/release/bundle/dmg/ChordPresenter_<version>_universal.dmg
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/../.." && pwd)"
cd "$ROOT"

# rustup's toolchain has the aarch64 target; Homebrew's Rust (if installed) doesn't.
export PATH="$HOME/.cargo/bin:$PATH"
VERSION="$(python3 -c "import json;print(json.load(open('src-tauri/tauri.conf.json'))['package']['version'])")"

echo "▸ Tests"
python3 -m unittest discover tests

echo "▸ Bundled Python"
scripts/build/bundle_python.sh

echo "▸ Universal build"
pnpm tauri build --target universal-apple-darwin --bundles app

BUNDLE="src-tauri/target/universal-apple-darwin/release/bundle"
APP="$BUNDLE/macos/ChordPresenter.app"

echo "▸ Check the app's own Python runs the scripts"
PY="$APP/Contents/Resources/python-runtime/$(uname -m | sed 's/arm64/aarch64/')/bin/python3.13"
env -i PATH=/bin PYTHONDONTWRITEBYTECODE=1 "$PY" -c \
  "import sys; sys.path.insert(0, '$APP/Contents/Resources/_up_/scripts'); import ew_fetch, md_to_pro; print('  ok:', md_to_pro._is_chord_token('Bm7b5'))"

echo "▸ Sign (ad-hoc)"
# Python must never write .pyc caches into the bundle — they'd break the signature.
find "$APP" -name '__pycache__' -type d -prune -exec rm -rf {} +
codesign --force --deep --sign - "$APP"
codesign --verify --deep --strict "$APP"

echo "▸ Package"
STAGE="$(mktemp -d)"
ditto "$APP" "$STAGE/ChordPresenter.app"
ln -s /Applications "$STAGE/Applications"
DMG="$BUNDLE/dmg/ChordPresenter_${VERSION}_universal.dmg"
mkdir -p "$(dirname "$DMG")"
hdiutil create -volname "ChordPresenter $VERSION" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
hdiutil verify "$DMG" >/dev/null
rm -rf "$STAGE"

echo "✓ $DMG ($(du -h "$DMG" | cut -f1))"
