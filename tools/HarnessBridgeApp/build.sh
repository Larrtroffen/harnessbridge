#!/usr/bin/env bash
# Build HarnessBridge.app.
#
#   ./build.sh              # PORTABLE release (default): embeds Python + backend + zstd,
#                           # builds the .app and dist/HarnessBridge-<version>-macos-arm64.dmg
#   ./build.sh --dev        # development build: app expects the repo workspace (no embedded runtime)
#   ./build.sh --dmg        # additionally build the DMG in --dev mode
#   ./build.sh --skip-build # reuse an existing .build binary
#   ./build.sh --debug      # debug configuration
#   ./build.sh --no-dmg     # portable app only, skip DMG creation
#
# Portable layout:
#   HarnessBridge.app/Contents/Resources/{python,backend/tools,bin/zstd}
#   (no workspace-path.txt → the app falls back to the bundled backend)
set -euo pipefail

APP_NAME="HarnessBridge"
BUNDLE_ID="io.github.larrtroffen.harnessbridge"
VERSION="1.6.2"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

CONFIG="release"
SKIP_BUILD=0
MODE="portable"     # portable | dev
BUILD_DMG=1
for arg in "$@"; do
  case "$arg" in
    --debug) CONFIG="debug" ;;
    --skip-build) SKIP_BUILD=1 ;;
    --dev) MODE="dev"; BUILD_DMG=0 ;;
    --portable) MODE="portable" ;;
    --dmg) BUILD_DMG=1 ;;
    --no-dmg) BUILD_DMG=0 ;;
    *) echo "unknown argument: $arg" >&2; exit 2 ;;
  esac
done

# Repo workspace root = nearest ancestor containing tools/agent-session-import/asi
WORKSPACE=""
DIR="$SCRIPT_DIR"
for _ in 1 2 3 4 5; do
  if [ -x "$DIR/tools/agent-session-import/asi" ]; then WORKSPACE="$DIR"; break; fi
  DIR="$(dirname "$DIR")"
done
if [ -z "$WORKSPACE" ]; then
  echo "ERROR: cannot locate repo workspace (tools/agent-session-import/asi). Portable builds need the source repo." >&2
  exit 2
fi

PY_VERSION="3.12.16+20261026"
PY_URL="https://github.com/astral-sh/python-build-standalone/releases/download/20261026/cpython-3.12.16+20261026-aarch64-apple-darwin-install_only.tar.gz"
PY_SHA256="fbf4afef53c2a6b72bb741bc06d5671a9dfaf87bd84e5aa73ac9b3d0d589f14e"
VENDOR_DIR="$SCRIPT_DIR/vendor"
VENDOR_PYTHON="$VENDOR_DIR/python"

ensure_python_runtime() {
  if [ -x "$VENDOR_PYTHON/bin/python3" ]; then
    echo "==> python runtime: $VENDOR_PYTHON ($("$VENDOR_PYTHON/bin/python3" --version 2>&1))"
    return 0
  fi
  mkdir -p "$VENDOR_DIR"
  local tar="$VENDOR_DIR/python-3.12.16.tar.gz"
  if [ ! -f "$tar" ]; then
    echo "==> downloading portable Python $PY_VERSION (~25MB)"
    curl -fL --retry 3 --max-time 300 -o "$tar" "$PY_URL"
  fi
  echo "==> verifying sha256"
  local actual
  actual="$(shasum -a 256 "$tar" | awk '{print $1}')"
  if [ "$actual" != "$PY_SHA256" ]; then
    echo "ERROR: python runtime sha256 mismatch: $actual != $PY_SHA256" >&2
    exit 2
  fi
  rm -rf "$VENDOR_PYTHON"
  tar -xzf "$tar" -C "$VENDOR_DIR"
  if [ ! -x "$VENDOR_PYTHON/bin/python3" ]; then
    echo "ERROR: unexpected python runtime layout (missing vendor/python/bin/python3)" >&2
    exit 2
  fi
  echo "==> python runtime: $VENDOR_PYTHON ($("$VENDOR_PYTHON/bin/python3" --version 2>&1))"
}

BIN=".build/$CONFIG/$APP_NAME"
if [ "$SKIP_BUILD" -eq 0 ]; then
  echo "==> swift build -c $CONFIG"
  export PATH="/opt/homebrew/bin:/opt/homebrew/sbin:$PATH"
  swift build -c "$CONFIG"
fi
if [ ! -x "$BIN" ]; then
  echo "ERROR: built binary not found: $BIN" >&2
  exit 2
fi

DIST="$SCRIPT_DIR/dist"
APP="$DIST/$APP_NAME.app"
DMG="$DIST/${APP_NAME}-${VERSION}-macos-arm64.dmg"
echo "==> assembling $APP (mode: $MODE)"
rm -rf "$APP"
mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp "$BIN" "$APP/Contents/MacOS/$APP_NAME"
chmod +x "$APP/Contents/MacOS/$APP_NAME"

if [ "$MODE" = "portable" ]; then
  ensure_python_runtime
  echo "==> embedding Python runtime"
  cp -R "$VENDOR_PYTHON" "$APP/Contents/Resources/python"
  echo "==> embedding backend"
  mkdir -p "$APP/Contents/Resources/backend/tools"
  cp -R "$WORKSPACE/tools/agent-session-import" "$APP/Contents/Resources/backend/tools/"
  cp "$WORKSPACE/tools/coverage-report.py" "$APP/Contents/Resources/backend/tools/"
  # Trim caches/output that must not ship.
  find "$APP/Contents/Resources/backend" -name '__pycache__' -type d -prune -exec rm -rf {} + 2>/dev/null || true
  rm -rf "$APP/Contents/Resources/backend/tools/agent-session-import/asi-out" 2>/dev/null || true
  chmod +x "$APP/Contents/Resources/backend/tools/agent-session-import/asi"
  # zstd (bundled so no Homebrew needed)
  ZSTD_SRC="$(command -v zstd || true)"
  [ -z "$ZSTD_SRC" ] && [ -x "$VENDOR_DIR/zstd" ] && ZSTD_SRC="$VENDOR_DIR/zstd"
  if [ -z "$ZSTD_SRC" ] || [ ! -x "$ZSTD_SRC" ]; then
    echo "ERROR: zstd binary not found (install zstd or put one at vendor/zstd)" >&2
    exit 2
  fi
  mkdir -p "$APP/Contents/Resources/bin" "$APP/Contents/Resources/lib"
  cp "$ZSTD_SRC" "$APP/Contents/Resources/bin/zstd"
  chmod +x "$APP/Contents/Resources/bin/zstd"
  # Homebrew zstd (and possible homebrew deps) → bundle dylibs and rewrite load paths.
  # Handles both absolute paths and @rpath references (zstd links @rpath/libzstd).
  if command -v install_name_tool >/dev/null 2>&1; then
    bundle_lib() {
      local ref="$1" target_bin="$2" base src
      case "$ref" in
        @rpath/*) base="${ref#@rpath/}"; src="$(find /opt/homebrew /usr/local -name "$base" 2>/dev/null | head -1)" ;;
        /*) base="$(basename "$ref")"; src="$ref" ;;
        *) return 0 ;;
      esac
      [ -n "${src:-}" ] && [ -f "$src" ] || return 0
      [ -f "$APP/Contents/Resources/lib/$base" ] || cp -L "$src" "$APP/Contents/Resources/lib/$base"
      install_name_tool -change "$ref" "@executable_path/../lib/$base" "$target_bin"
    }
    for ref in $(otool -L "$APP/Contents/Resources/bin/zstd" | awk 'NR>1 {print $1}' | grep -E '^(@rpath/|/opt/homebrew/|/usr/local/)' || true); do
      bundle_lib "$ref" "$APP/Contents/Resources/bin/zstd"
    done
    for dylib in "$APP/Contents/Resources/lib/"*.dylib; do
      [ -f "$dylib" ] || continue
      for ref2 in $(otool -L "$dylib" | awk 'NR>1 {print $1}' | grep -E '^(@rpath/|/opt/homebrew/|/usr/local/)' || true); do
        bundle_lib "$ref2" "$dylib"
      done
    done
  fi
  echo "==> portable: python=$("$APP/Contents/Resources/python/bin/python3" --version 2>&1) zstd=$("$APP/Contents/Resources/bin/zstd" --version 2>&1 | head -1)"
else
  echo "==> dev mode: workspace path marker"
  printf '%s\n' "$WORKSPACE" > "$APP/Contents/Resources/workspace-path.txt"
fi

# Optional harness logos (Assets/Logos/ or workspace assets/harness-logos).
LOGOS_SRC=""
if [ -d "$SCRIPT_DIR/Assets/Logos" ]; then
  LOGOS_SRC="$SCRIPT_DIR/Assets/Logos"
elif [ -d "${HARNESSBRIDGE_LOGOS_DIR:-${SESSION_CONVERTER_LOGOS_DIR:-}}" ]; then
  LOGOS_SRC="${HARNESSBRIDGE_LOGOS_DIR:-$SESSION_CONVERTER_LOGOS_DIR}"
elif [ -d "$WORKSPACE/assets/harness-logos" ]; then
  LOGOS_SRC="$WORKSPACE/assets/harness-logos"
fi
if [ -n "$LOGOS_SRC" ]; then
  mkdir -p "$APP/Contents/Resources/Logos"
  cp -R "$LOGOS_SRC"/. "$APP/Contents/Resources/Logos/" 2>/dev/null || true
  LOGO_COUNT=$(find "$APP/Contents/Resources/Logos" -type f \( -iname '*.png' -o -iname '*.jpg' -o -iname '*.jpeg' -o -iname '*.tiff' \) 2>/dev/null | wc -l | tr -d ' ')
  echo "==> logos: $LOGO_COUNT raster file(s)"
fi

# Optional app icon
ICON_PLIST=""
ICON_SRC="$SCRIPT_DIR/Assets/AppIcon.icns"
if [ -f "$ICON_SRC" ]; then
  cp "$ICON_SRC" "$APP/Contents/Resources/AppIcon.icns"
  ICON_PLIST="  <key>CFBundleIconFile</key><string>AppIcon</string>"
  echo "==> icon: Assets/AppIcon.icns"
fi

cat > "$APP/Contents/Info.plist" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>CFBundleDevelopmentRegion</key><string>zh_CN</string>
  <key>CFBundleExecutable</key><string>$APP_NAME</string>
  <key>CFBundleIdentifier</key><string>$BUNDLE_ID</string>
  <key>CFBundleInfoDictionaryVersion</key><string>6.0</string>
  <key>CFBundleName</key><string>$APP_NAME</string>
  <key>CFBundleDisplayName</key><string>$APP_NAME</string>
  <key>CFBundlePackageType</key><string>APPL</string>
  <key>CFBundleShortVersionString</key><string>$VERSION</string>
  <key>CFBundleVersion</key><string>1</string>
  <key>LSMinimumSystemVersion</key><string>13.0</string>
  <key>LSApplicationCategoryType</key><string>public.app-category.developer-tools</string>
  <key>NSHighResolutionCapable</key><true/>
  <key>NSPrincipalClass</key><string>NSApplication</string>
  <key>NSHumanReadableCopyright</key><string>HarnessBridge — Agent Session Converter</string>
$ICON_PLIST
</dict>
</plist>
PLIST

echo "==> ad-hoc codesign (embedded binaries first, then app)"
if [ "$MODE" = "portable" ]; then
  # codesign --deep does not cover arbitrary executables/dylibs under Resources;
  # sign every Mach-O we ship (python runtime, zstd, bundled dylibs).
  while IFS= read -r -d '' file; do
    if file "$file" | grep -q 'Mach-O'; then
      codesign --force --sign - "$file" >/dev/null 2>&1 || true
    fi
  done < <(find "$APP/Contents/Resources" -type f -print0 2>/dev/null)
fi
codesign --force --deep --sign - "$APP" 2>&1 | sed 's/^/    /'
codesign --verify --deep --strict "$APP"

if [ "$BUILD_DMG" -eq 1 ] && [ "$MODE" = "portable" ]; then
  echo "==> building DMG"
  rm -f "$DMG"
  hdiutil create -volname "$APP_NAME" -srcfolder "$APP" -ov -format UDZO "$DMG" >/dev/null
  DMG_MB=$(( $(stat -f%z "$DMG") / 1024 / 1024 ))
  echo "==> DMG: $DMG (${DMG_MB}MB)"
fi

echo ""
echo "Built: $APP"
if [ "$MODE" = "portable" ]; then
  echo "Portable: python+backend+zstd embedded, no workspace-path.txt"
fi
[ -f "$DMG" ] && echo "DMG:   $DMG"
echo "Run GUI:   open \"$APP\""
echo "Self-test: \"$APP/Contents/MacOS/$APP_NAME\" --self-test"
echo "Diagnose:  \"$APP/Contents/MacOS/$APP_NAME\" --diagnose"
