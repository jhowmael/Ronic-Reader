// Ronic Reader (iPad/iPhone): funciona offline depois da primeira visita.
// App: busca na rede primeiro (para receber atualizações) e cai no cache sem internet.
// Bibliotecas e modelo de voz (CDN e Hugging Face): cache primeiro (não mudam).
const APP = "ronic-app-v4", ASSETS = "ronic-assets-v1";
// Isolamento de origem (COOP/COEP): o GitHub Pages não deixa mandar esses cabeçalhos,
// então o service worker os acrescenta. Com isso a voz pode usar várias threads.
function isolate(res) {
  if (!res || res.status === 0 || res.type === "opaqueredirect") return res;
  const h = new Headers(res.headers);
  h.set("Cross-Origin-Opener-Policy", "same-origin");
  h.set("Cross-Origin-Embedder-Policy", "require-corp");
  h.set("Cross-Origin-Resource-Policy", "same-origin");
  return new Response(res.body, { status: res.status, statusText: res.statusText, headers: h });
}
const SHELL = ["./", "index.html", "backend.js", "manifest.webmanifest", "engine/text.js", "engine/formats.js",
  "engine/store.js", "engine/tts-worker.js", "engine/voices.json", "engine/vocab.json", "icons/icon-192.png", "icons/icon-512.png"];

self.addEventListener("install", (e) => { e.waitUntil(caches.open(APP).then((c) => c.addAll(SHELL)).then(() => self.skipWaiting())); });
self.addEventListener("activate", (e) => {
  // versões antigas guardavam os modelos de voz aqui também (cópia duplicada): libera o espaço
  e.waitUntil(caches.open(ASSETS).then(async (c) => { for (const r of await c.keys()) if (r.url.endsWith(".onnx")) await c.delete(r); }).catch(() => {}));
  e.waitUntil(caches.keys().then((ks) => Promise.all(ks.filter((k) => k !== APP && k !== ASSETS && !k.startsWith("ronic-models")).map((k) => caches.delete(k)))).then(() => self.clients.claim()));
});
self.addEventListener("fetch", (e) => {
  const url = new URL(e.request.url);
  if (e.request.method !== "GET") return;
  const external = /(^|\.)(jsdelivr\.net|huggingface\.co|hf\.co|xethub\.hf\.co)$/.test(url.hostname) || url.hostname.endsWith(".hf.co");
  if (external && url.pathname.endsWith(".onnx")) return;   // modelos grandes: a voz baixa e guarda sozinha
  if (external) {
    // entrega a resposta na hora e guarda no cache em paralelo (antes esperava baixar tudo
    // para o cache: a voz de ~90 MB parecia travada e ia inteira para a memória)
    e.respondWith(caches.open(ASSETS).then(async (c) => {
      const hit = await c.match(e.request);
      if (hit) return hit;
      const res = await fetch(e.request);
      if (res.ok) e.waitUntil(c.put(e.request, res.clone()).catch(() => {}));
      return res;
    }));
  } else if (url.origin === location.origin) {
    e.respondWith(fetch(e.request).then((res) => {
      if (res.ok) { const copy = res.clone(); caches.open(APP).then((c) => c.put(e.request, copy)); }
      return isolate(res);
    }).catch(() => caches.match(e.request, { ignoreSearch: true }).then(isolate)));
  }
});
