// Arquivo único para colar no painel do Cloudflare (gerado de gec.js + worker.js).
// Código Sec-MS-GEC (versão 2) exigido pelo serviço de voz do Edge: porte direto de
// edge_tts/drm.py (SHA-256 modificado + CS64). BigInt para ter a mesma aritmética do Python.
const M = 0xFFFFFFFFn;
const TOKEN = "6A5AA1D4EAFF4E9FB37E23D68491D6F4";
const INIT = [0x6A09E667n, 0xBB67AE85n, 0x3C6EF372n, 0xA54FF53An, 0x510E527Fn, 0x9B05688Cn, 0x1F83D9ABn, 0x5BE0CD19n];
const STATE = [0xFD9FBEA2n, 0x91243CE7n, 0xBE499094n, 0xCD2E1E0An, 0x6C006F49n, 0x04BD35ABn, 0xFEB0A7E4n, 0x03EFFBD2n];
const SCHED = [0xEB24BF9En, 0x1558691Fn, 0xA0C09EE2n, 0x0CFA32BAn, 0xA622EE8Cn, 0xD1DD9491n, 0xC0DD25A0n, 0xF9E70AB6n, 0xF0C31573n, 0x7058CE4En, 0x7188E606n, 0x00E5AB33n, 0xD258B060n, 0x72766564n];
const K = [0x428A2F98, 0x71374491, 0xB5C0FBCF, 0xE9B5DBA5, 0x3956C25B, 0x59F111F1, 0x923F82A4, 0xAB1C5ED5, 0xD807AA98, 0x12835B01, 0x243185BE, 0x550C7DC3, 0x72BE5D74, 0x80DEB1FE, 0x9BDC06A7, 0xC19BF174,
  0xE49B69C1, 0xEFBE4786, 0x0FC19DC6, 0x240CA1CC, 0x2DE92C6F, 0x4A7484AA, 0x5CB0A9DC, 0x76F988DA, 0x983E5152, 0xA831C66D, 0xB00327C8, 0xBF597FC7, 0xC6E00BF3, 0xD5A79147, 0x06CA6351, 0x14292967,
  0x27B70A85, 0x2E1B2138, 0x4D2C6DFC, 0x53380D13, 0x650A7354, 0x766A0ABB, 0x81C2C92E, 0x92722C85, 0xA2BFE8A1, 0xA81A664B, 0xC24B8B70, 0xC76C51A3, 0xD192E819, 0xD6990624, 0xF40E3585, 0x106AA070,
  0x19A4C116, 0x1E376C08, 0x2748774C, 0x34B0BCB5, 0x391C0CB3, 0x4ED8AA4A, 0x5B9CCA4F, 0x682E6FF3, 0x748F82EE, 0x78A5636F, 0x84C87814, 0x8CC70208, 0x90BEFFFA, 0xA4506CEB, 0xBEF9A3F7, 0xC67178F2].map(BigInt);
const ADJ = 0xC9DC06A7n;
const KB = [...K.slice(0, 14), ADJ, ...K.slice(15)];
const SIG0_ADJ = 0x059C0B80n, SIG1_ADJ = 0x000B92C0n;
const CS = [[0xE82E91B1n, 0xB32700D0n], [0x44DE24C6n, 0x88DFF51Dn], [0x3BEB65BCn, 0x29514038n], [0xC89C5933n, 0xB328CBDFn], [0x8D1EC211n, 0xD405B4D5n], [0x314EF5D5n, 0x26E55F3Cn], [0xE92491B1n, 0x607801C6n],
  [0xF0A5B9D5n, 0x82B2C1FBn], [0x06064CF3n, 0xFA51A3DAn], [0xDA79FA60n, 0x207CC464n], [0xBED20560n, 0x3C3C74F3n], [0x89F9C9F8n, 0xD2D14B61n], [0x35FA38C6n, 0xBB04A2C1n], [0xCB49E3C6n, 0xC5626167n]];
const CS_F = 0x82893933n, CS_A0 = 0xF2F90B1An, CS_A1 = 0x0B1A0000n;

const rol16 = (v) => { v &= M; return ((v << 16n) | (v >> 16n)) & M; };
const sigma0 = (v) => ((v >> 7n) ^ (v << 25n) ^ (v >> 18n) ^ (v << 14n) ^ (v >> 3n)) & M;
const sigma1 = (v) => ((v >> 17n) ^ (v << 15n) ^ (v >> 19n) ^ (v << 13n) ^ (v >> 10n)) & M;
const R = 0x100000001n;

function rounds(state, w, first = 0) {
  let [a, b, c, d, e, f, g, h] = state;
  const k = first === 14 ? KB : K;
  for (let i = first; i < 64; i++) {
    const re = e * R, ra = a * R;
    const t1 = h + ((re >> 6n) ^ (re >> 11n) ^ (re >> 25n)) + (g ^ (e & (f ^ g))) + k[i] + w[i];
    const t2 = ((ra >> 2n) ^ (ra >> 13n) ^ (ra >> 22n)) + ((a & b) | (c & (a | b)));
    [a, b, c, d, e, f, g, h] = [(t1 + t2) & M, a, b, c, (d + t1) & M, e, f, g];
  }
  return [a, b, c, d, e, f, g, h];
}
function expand(w, first = 16) {
  for (let i = first; i < 64; i++) {
    const x = w[i - 2], y = w[i - 15];
    const s1 = (x >> 17n) ^ (x << 15n) ^ (x >> 19n) ^ (x << 13n) ^ (x >> 10n);
    const s0 = (y >> 7n) ^ (y << 25n) ^ (y >> 18n) ^ (y << 14n) ^ (y >> 3n);
    w.push((s1 + w[i - 7] + s0 + w[i - 16]) & M);
  }
}
const beInt = (bytes) => bytes.reduce((n, x) => (n << 8n) | BigInt(x), 0n);
function shaInit(data) {
  const w = [...Array(14).fill(0n), beInt(data.slice(0, 3)), beInt(data.slice(3, 7))];
  for (let i = 16; i < 30; i++) {
    let v = SCHED[i - 16];
    if (i - 2 >= 14) v += i === 16 ? (sigma1(w[i - 2]) ^ SIG1_ADJ) : sigma1(w[i - 2]);
    if (i - 7 >= 14) v += w[i - 7];
    if (i - 15 >= 14) v += i === 29 ? (sigma0(w[i - 15]) ^ SIG0_ADJ) : sigma0(w[i - 15]);
    w.push(v & M);
  }
  w.push((sigma1(w[28]) + w[23] + sigma0(w[15]) + w[14] + ADJ - K[14]) & M);
  expand(w, 31);
  const work = rounds(STATE, w, 14);
  return INIT.map((x, i) => (x + work[i]) & M);
}
function sha(data) {
  const len = 57 + data.length;
  const pad = [...data.slice(7), 0x80, ...Array(((55 - len) % 64 + 64) % 64).fill(0)];
  const bits = BigInt(len * 8);
  for (let s = 56n; s >= 0n; s -= 8n) pad.push(Number((bits >> s) & 0xFFn));
  let state = shaInit(data.slice(0, 7));
  for (let o = 0; o < pad.length; o += 64) {
    const w = [];
    for (let j = 0; j < 16; j++) w.push(beInt(pad.slice(o + j * 4, o + j * 4 + 4)));
    expand(w);
    const work = rounds(state, w);
    state = state.map((x, i) => (x + work[i]) & M);
  }
  const out = [];
  for (const x of state) for (let s = 24n; s >= 0n; s -= 8n) out.push(Number((x >> s) & 0xFFn));
  return out;
}
const leWords = (bytes) => {
  const p = [...bytes, ...Array((4 - bytes.length % 4) % 4).fill(0)];
  const w = [];
  for (let i = 0; i < p.length; i += 4) w.push(BigInt(p[i]) | (BigInt(p[i + 1]) << 8n) | (BigInt(p[i + 2]) << 16n) | (BigInt(p[i + 3]) << 24n));
  if (w.length % 2) w.push(0n);
  return w;
};
function cs64(data, digest) {
  let [ka, kb] = leWords(digest.slice(0, 8));
  ka |= 1n; kb |= 1n;
  const fac = [(ka * CS_F) & M, (kb * CS_F) & M];
  const terms = CS.map(([c], i) => (c * fac[i % 2]) & M), offs = CS.map(([, o]) => o);
  leWords([0, ...data]).forEach((word, i) => {
    let term = word * (i % 2 === 0 ? ka : kb), off = rol16(word) * (i % 2 === 0 ? 0xEF0569FBn : 0xC31713DBn);
    if (i === 0) { term += CS_A0 * fac[0]; off += CS_A1; }
    terms.push(term & M); offs.push(off & M);
  });
  let swapAcc = 0n, swapLast = 0n, st = 0n, acc = 0n;
  for (let i = 0; i < terms.length; i += 2) {
    const x = terms[i], y = terms[i + 1];
    let t = rol16((offs[i] + x) & M), q = (t * 0x76F50F34n) & M;
    swapAcc += (rol16(q) * 0xC3EFEA97n + q) & M;
    t = rol16((offs[i + 1] + y) & M); q = (t * 0x1881CE3Cn) & M;
    swapLast = (rol16(q) * 0x35BD1EC9n + q) & M;
    swapAcc = (swapAcc + swapLast) & M;
    st = (st * ka + x) & M;
    st = (rol16(st) * 0xCF98B111n) & M; st = (rol16(st) * 0x87085B9Fn) & M;
    st = (rol16(st) * 0x12CEB96Dn) & M; st = (rol16(st) * 0x257E1D83n) & M;
    acc += st;
    t = (st * kb + y) & M;
    t = (rol16(t) * 0xA27416F5n) & M; t = (rol16(t) * 0xD38396FFn) & M;
    st = (rol16((rol16(t) * 0x7C932B89n) & M) * 0xBFA49F69n) & M;
    acc = (acc + st) & M;
  }
  return [swapLast ^ st, swapAcc ^ acc];
}
const hexBytes = (bytes) => bytes.map((b) => b.toString(16).padStart(2, "0")).join("").toUpperCase();
const leBytes = (v) => [0n, 8n, 16n, 24n].map((s) => Number((v >> s) & 0xFFn));

function secMsGec(unixSeconds = Date.now() / 1000) {
  let ticks = Math.floor(unixSeconds) + 11644473600;
  ticks -= ticks % 300;
  const str = `${BigInt(ticks) * 10000000n}${TOKEN}`;
  const data = [...new TextEncoder().encode(str)];
  const digest = sha(data);
  const [c1, c2] = cs64(data, digest);
  return `${hexBytes([...leBytes(c1), ...leBytes(c2)])}-${hexBytes(digest)}`;
}
// Ronic Reader: ponte para as vozes online (Francisca, Thalita, Antônio) na versão web.
// A Microsoft recusa conexões vindas de sites; este Worker conversa com ela como o app do Mac
// (edge-tts) e devolve o MP3. Só aceita pedidos do site do Ronic Reader e só essas três vozes.

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
