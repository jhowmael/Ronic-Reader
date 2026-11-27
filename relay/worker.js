// Ronic Reader: ponte para as vozes online (Francisca, Thalita, Antônio) na versão web.
// A Microsoft recusa conexões vindas de sites; este Worker conversa com ela como o app do Mac
// (edge-tts) e devolve o MP3. Só aceita pedidos do site do Ronic Reader e só essas três vozes.
import { secMsGec } from "./gec.js";

const VOICES = new Set(["pt-BR-FranciscaNeural", "pt-BR-ThalitaMultilingualNeural", "pt-BR-AntonioNeural"]);
const ORIGINS = ["https://jhowmael.github.io", "http://127.0.0.1:48767", "http://localhost:8080"];
const CHROMIUM = "143.0.3650.75";
const WSS = "https://speech.platform.bing.com/consumer/speech/synthesize/readaloud/edge/v1?TrustedClientToken=6A5AA1D4EAFF4E9FB37E23D68491D6F4";

const cors = (origin) => ({ "Access-Control-Allow-Origin": origin, "Access-Control-Allow-Methods": "POST, OPTIONS",
  "Access-Control-Allow-Headers": "Content-Type", "Access-Control-Max-Age": "86400", Vary: "Origin" });
const esc = (t) => t.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&apos;");
const sign = (v, unit, lo, hi) => { const n = Math.max(lo, Math.min(hi, parseInt(String(v || "0").replace(/[^\d+-]/g, ""), 10) || 0)); return `${n >= 0 ? "+" : ""}${n}${unit}`; };
const hex = (n) => [...crypto.getRandomValues(new Uint8Array(n))].map((b) => b.toString(16).padStart(2, "0")).join("");

// Abre a conversa com a Microsoft. Resolve quando chega o 1º pedaço de áudio (erros antes disso viram 502)
// e devolve o MP3 como um ReadableStream, que vai saindo aos poucos enquanto a Microsoft gera.
async function synthesize({ text, voice, rate, pitch, volume }) {
  const t0 = Date.now(), timing = {};
  const url = `${WSS}&ConnectionId=${hex(16)}&Sec-MS-GEC=${secMsGec()}&Sec-MS-GEC-Version=2-${CHROMIUM}`;
  const res = await fetch(url, { headers: {
    Upgrade: "websocket", Origin: "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    "User-Agent": `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0`,
    Pragma: "no-cache", "Cache-Control": "no-cache", Cookie: `muid=${hex(16).toUpperCase()};` } });
  const ws = res.webSocket;
  if (!ws) throw new Error(`Microsoft recusou a conexão (${res.status})`);
  ws.accept();
  timing.connect = Date.now() - t0;
  const ts = new Date().toString();
  let controller, gotFirst, failFirst, firstSeen = false, finished = false;
  const first = new Promise((ok, no) => { gotFirst = ok; failFirst = no; });
  const rest = new ReadableStream({ start(c) { controller = c; } });
  const timer = setTimeout(() => finish(new Error("sem resposta da Microsoft")), 25000);
  function finish(err) {
    if (finished) return; finished = true; clearTimeout(timer);
    try { ws.close(); } catch (e) {}
    timing.total = Date.now() - t0;
    if (!firstSeen) return failFirst(err || new Error("a Microsoft não devolveu áudio"));
    if (err) controller.error(err); else controller.close();
  }
  ws.addEventListener("message", (e) => {
    if (typeof e.data === "string") { if (e.data.includes("Path:turn.end")) finish(); return; }
    const b = new Uint8Array(e.data), hl = (b[0] << 8) | b[1];
    const head = new TextDecoder().decode(b.subarray(2, 2 + hl));
    if (!head.includes("Path:audio") || b.length <= 2 + hl) return;
    controller.enqueue(b.slice(2 + hl));
    if (!firstSeen) { firstSeen = true; timing.first = Date.now() - t0; gotFirst(); }
  });
  ws.addEventListener("close", () => finish());
  ws.addEventListener("error", () => finish(new Error("erro na conexão com a Microsoft")));
  ws.send(`X-Timestamp:${ts}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n` +
    '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}');
  // sempre pt-BR: com en-US as vozes multilíngues (Thalita) às vezes leem em inglês
  ws.send(`X-RequestId:${hex(16)}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${ts}Z\r\nPath:ssml\r\n\r\n` +
    `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='pt-BR'><voice name='${voice}'>` +
    `<prosody pitch='${sign(pitch, "Hz", -50, 50)}' rate='${sign(rate, "%", -50, 100)}' volume='${sign(volume, "%", -50, 50)}'>${esc(text)}</prosody></voice></speak>`);
  await first;
  return { rest, timing };
}

// mesmo texto + voz + ajustes = mesma chave de cache
async function cacheKey(body) {
  const raw = JSON.stringify([body.voice, sign(body.rate, "%", -50, 100), sign(body.pitch, "Hz", -50, 50), sign(body.volume, "%", -50, 50), body.text]);
  const d = new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(raw)));
  return new Request(`https://cache.ronic-reader/${[...d].map((b) => b.toString(16).padStart(2, "0")).join("")}.mp3`);
}

export default {
  async fetch(req, env, ctx) {
    const origin = req.headers.get("Origin") || "";
    if (!ORIGINS.includes(origin)) return new Response("Só para o Ronic Reader.", { status: 403 });
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
    if (req.method !== "POST") return new Response("Use POST.", { status: 405, headers: cors(origin) });
    try {
      const body = await req.json();
      const text = String(body.text || "").trim();
      if (!text || text.length > 3000) throw new Error("texto vazio ou longo demais");
      if (!VOICES.has(body.voice)) throw new Error("voz não permitida");
      const t0 = Date.now(), expose = { "Access-Control-Expose-Headers": "X-Cache, Server-Timing" };
      // 1) já gerado antes (mesmo texto, voz e ajustes)? sai do cache do Cloudflare na hora
      const key = await cacheKey({ ...body, text }), cache = caches.default;
      const hit = await cache.match(key);
      if (hit) return new Response(hit.body, { headers: { ...cors(origin), ...expose, "Content-Type": "audio/mpeg", "X-Cache": "HIT",
        "Server-Timing": `cache;dur=${Date.now() - t0}` } });
      // 2) gera na Microsoft e manda os pedaços conforme chegam; uma cópia vai para o cache
      const { rest, timing } = await synthesize({ ...body, text });
      const [toClient, toCache] = rest.tee();
      ctx.waitUntil(new Response(toCache).arrayBuffer().then((buf) => buf.byteLength &&
        cache.put(key, new Response(buf, { headers: { "Content-Type": "audio/mpeg", "Cache-Control": "public, max-age=2592000" } }))).catch(() => {}));
      return new Response(toClient, { headers: { ...cors(origin), ...expose, "Content-Type": "audio/mpeg", "Cache-Control": "no-store", "X-Cache": "MISS",
        "Server-Timing": `connect;dur=${timing.connect}, first;dur=${timing.first}` } });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e) }), { status: 502, headers: { ...cors(origin), "Content-Type": "application/json" } });
    }
  },
};
