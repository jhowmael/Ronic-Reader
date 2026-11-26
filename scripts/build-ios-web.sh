#!/usr/bin/env bash
# Builds the iPad/iPhone web app (GitHub Pages) into build/ios-web.
# The interface is the same file as the macOS app (ronic_reader/web/index.html); in the browser
# the "server" is ios-web/backend.js and the Kokoro voice runs in a Web Worker on the device.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
OUT="$ROOT/build/ios-web"
PY="${PY:-python3}"
rm -rf "$OUT"
mkdir -p "$OUT"
cp -R "$ROOT/ios-web/." "$OUT/"
[[ -f "$OUT/icons/icon-512.png" ]] || "$ROOT/branding/make-icons.sh"
cp "$ROOT/exemplos/exemplo.pdf" "$OUT/exemplo.pdf" 2>/dev/null || true
"$PY" - "$ROOT" "$OUT" <<'PYEOF'
import json, re, sys
from pathlib import Path
root, out = Path(sys.argv[1]), Path(sys.argv[2])
sys.path.insert(0, str(root))
from ronic_reader import voices  # catálogo único (o mesmo do app do Mac)
(out / "engine/voices.json").write_text(json.dumps([v for v in voices.catalog() if v["engine"] == "kokoro"], ensure_ascii=False))
vocab = json.loads((root / "ios-web/engine/vocab.json").read_text())
html = (root / "ronic_reader/web/index.html").read_text(encoding="utf-8")
html = html.replace("__RONIC_TOKEN__", "web")
head = """<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="Ronic Reader">
<meta name="theme-color" content="#ebeaef" media="(prefers-color-scheme: light)">
<meta name="theme-color" content="#161618" media="(prefers-color-scheme: dark)">
<link rel="manifest" href="manifest.webmanifest">
<link rel="apple-touch-icon" href="icons/icon-180.png">
<link rel="icon" type="image/png" href="icons/icon-192.png">
<script src="backend.js"></script>"""
html = re.sub(r'<meta name="viewport"[^>]*>', head, html, count=1)
(out / "index.html").write_text(html, encoding="utf-8")
print("site:", out, "| vozes:", len(json.loads((out / "engine/voices.json").read_text())), "| vocab:", len(vocab))
PYEOF
