#!/bin/bash
# Build an unsigned, self-contained universal macOS 13+ release bundle.
#
# Run this on macOS with a universal2 Python 3.12 interpreter. The script
# fails if its interpreter or any bundled Mach-O binary is not universal, so
# an Intel-only or Apple-Silicon-only artifact cannot be shipped accidentally.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
PYTHON="${PYTHON:-python3}"
BUILD_DIR="${BUILD_DIR:-$ROOT/build/release}"
DIST_DIR="${DIST_DIR:-$ROOT/dist}"
APP_NAME="FokusKeeper"
APP_PATH="$DIST_DIR/$APP_NAME.app"
DMG_PATH="$DIST_DIR/$APP_NAME.dmg"

require_universal() {
  local binary="$1"
  local architectures
  architectures="$(lipo -archs "$binary" 2>/dev/null || true)"
  if [[ " $architectures " != *" x86_64 "* || " $architectures " != *" arm64 "* ]]; then
    echo "Expected a universal x86_64 + arm64 binary, got '$architectures': $binary" >&2
    exit 1
  fi
}

validate_bundle() {
  local file_path found=0
  while IFS= read -r -d '' file_path; do
    if file "$file_path" | grep -q 'Mach-O'; then
      found=1
      require_universal "$file_path"
    fi
  done < <(find "$APP_PATH" -type f -print0)

  if [[ "$found" != 1 ]]; then
    echo "No Mach-O files found in $APP_PATH" >&2
    exit 1
  fi

  /usr/libexec/PlistBuddy -c 'Print :LSMinimumSystemVersion' \
    "$APP_PATH/Contents/Info.plist" | grep -qx '13.0'
}

rm -rf "$BUILD_DIR" "$APP_PATH" "$DMG_PATH"
mkdir -p "$BUILD_DIR" "$DIST_DIR"

require_universal "$($PYTHON -c 'import sys; print(sys.executable)')"
"$PYTHON" -m pip install --upgrade pip
"$PYTHON" -m pip install -r "$ROOT/requirements.txt" -r "$ROOT/requirements-release.txt"

export MACOSX_DEPLOYMENT_TARGET=13.0

# The daemon is a separate frozen executable. The menu-bar executable launches
# it by the sibling path inside the app bundle, leaving no Python runtime or
# source files required after installation.
"$PYTHON" -m PyInstaller --noconfirm --clean --onefile \
  --name FokusKeeperDaemon \
  --target-architecture universal2 \
  --hidden-import fokuskeeper_settings_panel \
  --distpath "$BUILD_DIR/daemon-dist" \
  --workpath "$BUILD_DIR/daemon-work" \
  --specpath "$BUILD_DIR/spec" \
  "$ROOT/fokuskeeper.py"

"$PYTHON" -m PyInstaller --noconfirm --clean --windowed \
  --name "$APP_NAME" \
  --target-architecture universal2 \
  --osx-bundle-identifier io.github.cipshadow.fokuskeeper \
  --icon "$ROOT/assets/FokusKeeper.icns" \
  --distpath "$DIST_DIR" \
  --workpath "$BUILD_DIR/menubar-work" \
  --specpath "$BUILD_DIR/spec" \
  "$ROOT/fokuskeeper_menubar.py"

cp "$BUILD_DIR/daemon-dist/FokusKeeperDaemon" "$APP_PATH/Contents/MacOS/FokusKeeperDaemon"
chmod +x "$APP_PATH/Contents/MacOS/FokusKeeperDaemon"
/usr/libexec/PlistBuddy -c 'Add :LSMinimumSystemVersion string 13.0' \
  "$APP_PATH/Contents/Info.plist"
/usr/libexec/PlistBuddy -c 'Add :LSUIElement bool true' \
  "$APP_PATH/Contents/Info.plist"

# PyInstaller signs its bundle before we add the daemon and minimum-version
# metadata. Re-sign the completed bundle ad hoc so macOS sees a structurally
# valid unsigned app instead of a bundle whose signature was modified later.
codesign --force --deep --sign - "$APP_PATH"
codesign --verify --deep --strict --verbose=2 "$APP_PATH"

validate_bundle

# A read-only DMG is easy to install: open it and drag FokusKeeper.app to
# Applications. No source checkout, Homebrew, or Python is part of the route.
STAGE="$BUILD_DIR/dmg-stage"
mkdir -p "$STAGE"
cp -R "$APP_PATH" "$STAGE/$APP_NAME.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "$APP_NAME" -srcfolder "$STAGE" -ov -format UDZO "$DMG_PATH"
(cd "$DIST_DIR" && shasum -a 256 "$(basename "$DMG_PATH")" > "$(basename "$DMG_PATH").sha256")

echo "Built and validated: $DMG_PATH"
