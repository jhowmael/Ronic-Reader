#!/usr/bin/env bash
# Packages Ronic Reader for macOS (Apple Silicon):
#   dist/Ronic Reader.app
#   dist/RonicReader-macOS.zip   (ready to attach to GitHub Releases)
#   dist/RonicReader.dmg         (drag-and-drop installer)
#
# Optional variables:
#   VERSION=1.0.0            version written to Info.plist
#   SIGN_IDENTITY="Developer ID Application: Jane Doe (TEAMID)"   real signing (default: ad-hoc "-")
#   PYTHON=python3.13        Python used to create .venv when it does not exist
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"
VERSION="${VERSION:-$(sed -n 's/^__version__ = "\(.*\)"/\1/p' ronic_reader/__init__.py)}"
SIGN_IDENTITY="${SIGN_IDENTITY:--}"
DIST="$ROOT/dist"
APP="$DIST/Ronic Reader.app"

echo "==> Ronic Reader $VERSION (macOS)"

# 1) Python environment with the app and PyInstaller
if [[ ! -x "$ROOT/.venv/bin/python" ]]; then
  echo "==> Creating .venv"
  "${PYTHON:-python3.13}" -m venv "$ROOT/.venv"
fi
PY="$ROOT/.venv/bin/python"
echo "==> Installing dependencies"
if "$PY" -m pip --version >/dev/null 2>&1; then
  "$PY" -m pip install -q --upgrade pip
  "$PY" -m pip install -q -e ".[offline,app]" pyinstaller
else  # venv criado pelo uv (sem pip)
  uv pip install -q --python "$PY" -e ".[offline,app]" pyinstaller
fi

# 2) Icon (branding/make-logo.swift -> packaging/RonicReader.icns)
if [[ ! -f "$ROOT/packaging/RonicReader.icns" ]]; then
  "$ROOT/branding/make-icons.sh"
fi

# 3) .app bundle
echo "==> Building the app (PyInstaller, a few minutes)"
rm -rf "$APP"
(cd packaging && "$PY" -m PyInstaller --noconfirm --clean --log-level WARN \
  --distpath "$DIST" --workpath "$ROOT/build" RonicReader.spec)
plutil -replace CFBundleShortVersionString -string "$VERSION" "$APP/Contents/Info.plist"
plutil -replace CFBundleVersion -string "$(date +%Y%m%d%H%M)" "$APP/Contents/Info.plist"

# 4) Signing (ad-hoc by default)
echo "==> Signing ($SIGN_IDENTITY)"
SIGN_FLAGS=(--force --deep --sign "$SIGN_IDENTITY")
if [[ "$SIGN_IDENTITY" == Developer\ ID* ]]; then
  SIGN_FLAGS+=(--options runtime --timestamp)
fi
codesign "${SIGN_FLAGS[@]}" "$APP"
codesign --verify --deep --strict "$APP"

# 5) Zip for GitHub Releases (ditto keeps the signature and attributes)
ZIP="$DIST/RonicReader-macOS.zip"
rm -f "$ZIP"
ditto -c -k --keepParent "$APP" "$ZIP"

# 6) Drag-and-drop installer: the app next to a shortcut to /Applications
DMG="$DIST/RonicReader.dmg"
STAGE="$DIST/dmg-stage"
rm -rf "$STAGE" "$DMG"
mkdir -p "$STAGE"
ditto "$APP" "$STAGE/Ronic Reader.app"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "Ronic Reader" -srcfolder "$STAGE" -ov -format UDZO "$DMG" >/dev/null
rm -rf "$STAGE"

echo
echo "Done:"
echo "  App: $APP"
echo "  Zip: $ZIP"
echo "  Dmg: $DMG"
if [[ "${INSTALL:-0}" == "1" ]]; then
  rm -rf "$HOME/Applications/Ronic Reader.app"
  ditto "$APP" "$HOME/Applications/Ronic Reader.app"
  echo "  Installed in ~/Applications"
fi
