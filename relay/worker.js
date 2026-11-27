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

async function synthesize({ text, voice, rate, pitch, volume }) {
  const url = `${WSS}&ConnectionId=${hex(16)}&Sec-MS-GEC=${secMsGec()}&Sec-MS-GEC-Version=2-${CHROMIUM}`;
  const res = await fetch(url, { headers: {
    Upgrade: "websocket", Origin: "chrome-extension://jdiccldimpdaibmpdkjnbmckianbfold",
    "User-Agent": `Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/143.0.0.0 Safari/537.36 Edg/143.0.0.0`,
    Pragma: "no-cache", "Cache-Control": "no-cache", Cookie: `muid=${hex(16).toUpperCase()};` } });
  const ws = res.webSocket;
  if (!ws) throw new Error(`Microsoft recusou a conexão (${res.status})`);
  ws.accept();
  const ts = new Date().toString();
  const chunks = [];
  const done = new Promise((resolve, reject) => {
    const timer = setTimeout(() => reject(new Error("sem resposta da Microsoft")), 25000);
    ws.addEventListener("message", (e) => {
      if (typeof e.data === "string") { if (e.data.includes("Path:turn.end")) { clearTimeout(timer); resolve(); } return; }
      const b = new Uint8Array(e.data), hl = (b[0] << 8) | b[1];
      const head = new TextDecoder().decode(b.subarray(2, 2 + hl));
      if (head.includes("Path:audio") && b.length > 2 + hl) chunks.push(b.subarray(2 + hl));
    });
    ws.addEventListener("close", () => { clearTimeout(timer); resolve(); });
    ws.addEventListener("error", () => { clearTimeout(timer); reject(new Error("erro na conexão com a Microsoft")); });
  });
  ws.send(`X-Timestamp:${ts}\r\nContent-Type:application/json; charset=utf-8\r\nPath:speech.config\r\n\r\n` +
    '{"context":{"synthesis":{"audio":{"metadataoptions":{"sentenceBoundaryEnabled":"false","wordBoundaryEnabled":"false"},"outputFormat":"audio-24khz-48kbitrate-mono-mp3"}}}}');
  // sempre pt-BR: com en-US as vozes multilíngues (Thalita) às vezes leem em inglês
  ws.send(`X-RequestId:${hex(16)}\r\nContent-Type:application/ssml+xml\r\nX-Timestamp:${ts}Z\r\nPath:ssml\r\n\r\n` +
    `<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='pt-BR'><voice name='${voice}'>` +
    `<prosody pitch='${sign(pitch, "Hz", -50, 50)}' rate='${sign(rate, "%", -50, 100)}' volume='${sign(volume, "%", -50, 50)}'>${esc(text)}</prosody></voice></speak>`);
  await done;
  try { ws.close(); } catch (e) {}
  const total = chunks.reduce((n, c) => n + c.length, 0), out = new Uint8Array(total);
  let o = 0; for (const c of chunks) { out.set(c, o); o += c.length; }
  if (!total) throw new Error("a Microsoft não devolveu áudio");
  return out;
}

export default {
  async fetch(req) {
    const origin = req.headers.get("Origin") || "";
    if (!ORIGINS.includes(origin)) return new Response("Só para o Ronic Reader.", { status: 403 });
    if (req.method === "OPTIONS") return new Response(null, { status: 204, headers: cors(origin) });
    if (req.method !== "POST") return new Response("Use POST.", { status: 405, headers: cors(origin) });
    try {
      const body = await req.json();
      const text = String(body.text || "").trim();
      if (!text || text.length > 3000) throw new Error("texto vazio ou longo demais");
      if (!VOICES.has(body.voice)) throw new Error("voz não permitida");
      const mp3 = await synthesize({ ...body, text });
      return new Response(mp3, { headers: { ...cors(origin), "Content-Type": "audio/mpeg", "Cache-Control": "no-store" } });
    } catch (e) {
      return new Response(JSON.stringify({ error: String(e.message || e) }), { status: 502, headers: { ...cors(origin), "Content-Type": "application/json" } });
    }
  },
};
