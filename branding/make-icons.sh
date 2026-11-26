#!/usr/bin/env bash
# Generates the Ronic Reader logo and icons from branding/make-logo.swift.
# Run on macOS:  ./branding/make-icons.sh
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/branding/out"
rm -rf "$OUT"
mkdir -p "$OUT"
swift "$ROOT/branding/make-logo.swift" "$OUT/logo-1024.png"

# README / GitHub
sips -z 512 512 "$OUT/logo-1024.png" --out "$ROOT/branding/logo.png" >/dev/null

# macOS (.icns)
ICONSET="$OUT/AppIcon.iconset"
mkdir -p "$ICONSET"
for s in 16 32 128 256 512; do
  sips -z "$s" "$s" "$OUT/logo-1024.png" --out "$ICONSET/icon_${s}x${s}.png" >/dev/null
  d=$((s * 2)); sips -z "$d" "$d" "$OUT/logo-1024.png" --out "$ICONSET/icon_${s}x${s}@2x.png" >/dev/null
done
iconutil -c icns "$ICONSET" -o "$ROOT/packaging/RonicReader.icns"

# iPad / iPhone (web app on GitHub Pages): full-bleed square, iOS rounds the corners itself
mkdir -p "$ROOT/ios-web/icons"
sips -c 920 920 "$OUT/logo-1024.png" --out "$OUT/square.png" >/dev/null
for s in 180 192 512; do
  sips -z "$s" "$s" "$OUT/square.png" --out "$ROOT/ios-web/icons/icon-$s.png" >/dev/null
done
cp "$ROOT/branding/logo.png" "$ROOT/ios-web/icons/logo.png"
echo "OK"
