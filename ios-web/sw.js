// Ronic Reader (iPad/iPhone): funciona offline depois da primeira visita.
// App: busca na rede primeiro (para receber atualizações) e cai no cache sem internet.
// Bibliotecas e modelo de voz (CDN e Hugging Face): cache primeiro (não mudam).
const APP = "ronic-app-v1", ASSETS = "ronic-assets-v1";
const SHELL = ["./", "index.html", "backend.js", "manifest.webmanifest", "engine/text.js", "engine/formats.js",
  "engine/store.js", "engine/tts-worker.js", "engine/voices.json", "engine/vocab.json", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => { e.waitUntil(caches.open(APP).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => { e.waitUntil(self.clients.claim()); });
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  const external = /(^|\.)(jsdelivr\.net|huggingface\.co|hf\.co|xethub\.hf\.co)$/.test(url.hostname) || url.hostname.endsWith(".hf.co");
  if (external) {
    e.respondWith(caches.open(ASSETS).then(async (c) => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) await c.put(e.request, res.clone());
      return res;
    }));
  } else if (url.origin === location.origin) {
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(APP).then((c) => c.put(e.request, copy)); }
      return res;
    }).catch(() => caches.match(e.request, { ignoreSearch: true })));
  }
});
