// Ronic Reader (iPad/iPhone/navegador): vozes geradas no próprio aparelho.
// Dois motores, ambos com fonemas do espeak-ng (WebAssembly) e ONNX Runtime Web (CPU, várias threads):
//  - Piper (pt_BR faber, cadu, jeff): vozes treinadas com falantes brasileiros, leves e rápidas.
//  - Kokoro: mais pesado; com o ajuste de sotaque do app do Mac ("y"->"i", "æ"->"ɐ").
const PIPER = "https://cdn.jsdelivr.net/npm/@diffusionstudio/piper-wasm@1.0.0/build/piper_phonemize";
const ORT = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/";
const HF = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/";
const PIPER_HF = "https://huggingface.co/rhasspy/piper-voices/resolve/main/pt/pt_BR/";
const KOKORO_SR = 24000, SENTENCE_PAUSE = 0.18, PARAGRAPH_PAUSE = 0.45;

importScripts(PIPER + ".js", ORT + "ort.webgpu.min.js");
ort.env.wasm.wasmPaths = ORT;
// com isolamento (cabeçalhos do sw.js) o modelo roda em várias threads
if (self.crossOriginIsolated) ort.env.wasm.numThreads = Math.max(1, Math.min(4, (self.navigator.hardwareConcurrency || 2) - 1));
// iPhone/iPad: menos threads (memória curta; o sistema derruba o Worker se passar do limite)
if (/iPhone|iPad|Mobile/.test(self.navigator.userAgent)) ort.env.wasm.numThreads = Math.min(ort.env.wasm.numThreads || 1, 2);
const THREADS = ort.env.wasm.numThreads || 1;

// ------------------------------------------------------------------ modelos
async function download(url, label, approx) {
  const res = await fetch(url);
  if (!res.ok) throw new Error("Sem internet para baixar a voz (só na primeira vez).");
  const total = +res.headers.get("content-length") || approx, reader = res.body.getReader(), parts = [];
  let got = 0, shown = -1;
  for (;;) {
    const { done, value } = await reader.read(); if (done) break;
    parts.push(value); got += value.length;
    const p = Math.min(99, Math.floor(got / total * 100));
    if (p !== shown && p % 5 === 0) { shown = p; postMessage({ type: "status", phase: "download", text: `Baixando ${label} ${p}% (só na primeira vez)` }); }
  }
  const out = new Uint8Array(got); let o = 0;
  for (const c of parts) { out.set(c, o); o += c.length; }
  return out;
}
async function createSession(model, ep = "wasm") {
  postMessage({ type: "status", phase: "load", text: "Carregando a voz…" });
  if (ep === "webgpu") return Promise.race([ort.InferenceSession.create(model, { executionProviders: ["webgpu"] }),
    new Promise((_, no) => setTimeout(() => no(new Error("prazo")), 30000))]);
  // CPU com threads, senão CPU simples; cada tentativa tem prazo para nunca travar.
  // (WebGPU fica de fora: com o Kokoro quantizado ele gera ruído no lugar da fala.)
  const tries = self.crossOriginIsolated && THREADS > 1 ? [THREADS, 1] : [1];
  for (const threads of tries) {
    ort.env.wasm.numThreads = threads;
    try {
      return await Promise.race([ort.InferenceSession.create(model, { executionProviders: ["wasm"] }),
        new Promise((_, no) => setTimeout(() => no(new Error("prazo")), 30000))]);
    } catch (e) { /* tenta a próxima */ }
  }
  throw new Error("Não foi possível carregar a voz neste aparelho.");
}

// Kokoro: na placa de vídeo (WebGPU) com o modelo completo é ~4x mais rápido que a fala (medido);
// sem WebGPU, modelo compacto no processador. (O compacto e o fp16 na GPU geram ruído: medido com reconhecedor.)
let vocab = null, kokoro = null;
const styles = new Map();
async function gpuAvailable() {
  try { return !!(self.navigator.gpu && await self.navigator.gpu.requestAdapter()); } catch (e) { return false; }
}
async function loadKokoro(vocabUrl, allowGpu = true) {
  if (kokoro) return kokoro;
  vocab ||= await (await fetch(vocabUrl)).json();
  if (allowGpu && await gpuAvailable()) {
    try {
      kokoro = await createSession(await download(HF + "onnx/model.onnx", "a voz", 326e6), "webgpu");
      postMessage({ type: "ready", device: "webgpu" });
      return kokoro;
    } catch (e) { kokoro = null; }
  }
  kokoro = await createSession(await download(HF + "onnx/model_quantized.onnx", "a voz", 92e6));
  postMessage({ type: "ready", device: "wasm" });
  return kokoro;
}
async function voiceRows(name) {
  if (!styles.has(name)) styles.set(name, new Float32Array(await (await fetch(HF + `voices/${name}.bin`)).arrayBuffer()));
  return styles.get(name);
}
// "pf_dora" ou mistura "mix:pm_alex*0.6+bm_george*0.4"
async function styleFor(voice) {
  if (!voice.startsWith("mix:")) return voiceRows(voice);
  let out = null;
  for (const term of voice.slice(4).split("+")) {
    const [name, w] = term.split("*"); const v = await voiceRows(name.trim()); const k = parseFloat(w || "1");
    if (!out) out = new Float32Array(v.length);
    for (let i = 0; i < v.length; i++) out[i] += v[i] * k;
  }
  return out;
}
async function kokoroSpeak(ph, style, speed) {
  const ids = [...ph].map((c) => vocab[c]).filter((x) => x !== undefined).slice(0, 508);
  if (!ids.length) return new Float32Array(0);
  const row = Math.min(ids.length, 510) - 1;
  const feeds = {
    [kokoro.inputNames[0]]: new ort.Tensor("int64", BigInt64Array.from([0, ...ids, 0].map(BigInt)), [1, ids.length + 2]),
    style: new ort.Tensor("float32", style.slice(row * 256, row * 256 + 256), [1, 256]),
    speed: new ort.Tensor("float32", Float32Array.from([speed]), [1]),
  };
  return (await kokoro.run(feeds))[kokoro.outputNames[0]].data;
}

// Piper: um modelo por voz; só um fica na memória
const piper = { name: null, session: null, cfg: null };
async function loadPiper(name) {
  if (piper.name === name) return piper;
  if (piper.session) { try { await piper.session.release(); } catch (e) {} piper.session = null; piper.name = null; }
  const [, speaker, quality] = name.split("-");   // pt_BR-faber-medium
  const base = `${PIPER_HF}${speaker}/${quality}/${name}.onnx`;
  piper.cfg = await (await fetch(base + ".json")).json();
  const label = speaker[0].toUpperCase() + speaker.slice(1);
  piper.session = await createSession(await download(base, `a voz ${label}`, 63e6));
  piper.name = name;
  postMessage({ type: "ready" });
  return piper;
}
async function piperSpeak(ph, speed, expressiveness) {
  const map = piper.cfg.phoneme_id_map, inf = piper.cfg.inference || {};
  const ids = [...map["^"], ...map["_"]];
  for (const c of ph) { const id = map[c]; if (id) ids.push(...id, ...map["_"]); }
  ids.push(...map["$"]);
  if (ids.length <= 3) return new Float32Array(0);
  const noise = (inf.noise_scale ?? 0.667) * (0.4 + 0.9 * (expressiveness ?? 0.667));   // expressividade
  const feeds = {
    input: new ort.Tensor("int64", BigInt64Array.from(ids.map(BigInt)), [1, ids.length]),
    input_lengths: new ort.Tensor("int64", BigInt64Array.from([BigInt(ids.length)]), [1]),
    scales: new ort.Tensor("float32", Float32Array.from([noise, (inf.length_scale ?? 1) / speed, inf.noise_w ?? 0.8]), [3]),
  };
  return (await piper.session.run(feeds))[piper.session.outputNames[0]].data;
}

// ------------------------------------------------------------------ fonemas
// espeak-ng é criado uma vez e reaproveitado
let phonemizer = null;
function phonemize(text) {
  return new Promise(async (resolve, reject) => {
    // nunca fica esperando para sempre: sem resposta em 15 s, recria o espeak e avisa o erro
    const timer = setTimeout(() => { phonemizer = null; reject(new Error("fonemas sem resposta")); }, 15000);
    const done = (ph) => { clearTimeout(timer); resolve(ph); };
    const run = (m) => {
      m._resolve = done;
      try { m.callMain(["-l", "pt-br", "--input", JSON.stringify([{ text }]), "--espeak_data", "/espeak-ng-data"]); }
      catch (e) { clearTimeout(timer); phonemizer = null; reject(e); }
    };
    if (!phonemizer) {
      const holder = {};
      phonemizer = await createPiperPhonemize({
        // fonemas por frase (texto ou lista de símbolos), separados por espaço: juntos, viravam uma frase
        // gigante cortada no fim. Marcas de troca de idioma ("(en)") saem: a leitura fica sempre em pt-BR.
        print: (d) => {
          let j; try { j = JSON.parse(d); } catch (e) { return; /* linha extra */ }
          const ph = (j.phonemes || []).map((s) => (Array.isArray(s) ? s.join("") : String(s))).join(" ");
          holder.m._resolve(ph.replace(/\([a-z]{2,3}(?:-[a-z]+)?\)/gi, ""));
        },
        printErr: () => {},
        locateFile: (u) => (u.endsWith(".wasm") ? PIPER + ".wasm" : u.endsWith(".data") ? PIPER + ".data" : u),
      });
      holder.m = phonemizer;
    }
    run(phonemizer);
  });
}
const ptbr = (ph) => ph.replace(/y/g, "i").replace(/æ/g, "ɐ");
// frases do texto em fonemas, sem passar de ~250 símbolos por inferência
function phonemeSentences(ph) {
  const out = []; let cur = "";
  for (const piece of ph.split(/(?<=[.!?…,;:])\s+/)) {
    if (cur && cur.length + piece.length > 250) { out.push(cur); cur = piece; }
    else cur = cur ? cur + " " + piece : piece;
  }
  if (cur) out.push(cur);
  // frase sem pontuação maior que o limite: corta nos espaços
  return out.flatMap((s) => {
    if (s.length <= 300) return [s];
    const parts = []; let rest = s;
    while (rest.length > 250) { let cut = rest.lastIndexOf(" ", 250); if (cut <= 0) cut = 250; parts.push(rest.slice(0, cut)); rest = rest.slice(cut).trim(); }
    if (rest) parts.push(rest);
    return parts;
  });
}

// ------------------------------------------------------------------ áudio
function resample(data, from, to) {
  if (from === to) return data;
  const n = Math.round(data.length * to / from), out = new Float32Array(n), r = from / to;
  for (let i = 0; i < n; i++) { const x = i * r, k = Math.floor(x), f = x - k; out[i] = (data[k] || 0) * (1 - f) + (data[k + 1] || 0) * f; }
  return out;
}
function wav(chunks, sr) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const buf = new ArrayBuffer(44 + total * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + total * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, sr, true);
  v.setUint32(28, sr * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, total * 2, true);
  let o = 44;
  for (const c of chunks) for (let i = 0; i < c.length; i++, o += 2) v.setInt16(o, Math.max(-1, Math.min(1, c[i])) * 32767, true);
  return buf;
}
const isPiper = (voice) => voice.startsWith("piper:");
async function synth(voice, text, job) {
  const out = [];
  if (isPiper(voice)) {
    await loadPiper(voice.slice(6));
    const sr = piper.cfg.audio.sample_rate;
    for (const s of phonemeSentences(await phonemize(text))) {
      out.push(resample(await piperSpeak(s, job.speed, job.expressiveness), sr, job.sr));
      out.push(new Float32Array(Math.round(job.sr * SENTENCE_PAUSE)));
    }
  } else {
    await loadKokoro(job.vocab, job.gpu !== false);
    const style = await styleFor(voice);
    // tom: gera um pouco mais devagar e acelera reamostrando (a duração fica igual, a voz sobe/desce)
    const f = job.pitch || 1;
    for (const s of phonemeSentences(ptbr(await phonemize(text)))) {
      let a = await kokoroSpeak(s, style, job.speed / f);
      if (Math.abs(f - 1) > 0.01) a = resample(a, f, 1);
      out.push(resample(a, KOKORO_SR, job.sr));
      out.push(new Float32Array(Math.round(job.sr * SENTENCE_PAUSE * (job.pause ?? 1))));
    }
  }
  return out;
}

// fila: cada pedido vira parágrafos; entre um e outro, pedidos mais urgentes passam na frente
const queue = []; let busy = false;
function units(job) {
  const out = [];
  for (const part of job.parts) for (const para of part.text.split("\n\n")) if (para.trim()) out.push({ voice: part.voice, text: para.trim(), para: true });
  // pedaço no meio de um parágrafo: só a pausa de frase no fim (a de parágrafo quebraria o ritmo)
  const last = job.parts[job.parts.length - 1];
  if (out.length && last?.end === "sentence") out[out.length - 1].para = false;
  return out;
}
async function pump() {
  if (busy || !queue.length) return;
  busy = true;
  queue.sort((a, b) => b.priority - a.priority || a.id - b.id);
  const job = queue[0];
  try {
    job.units ||= units(job); job.chunks ||= [];
    job.sr ||= job.parts.every((p) => isPiper(p.voice)) ? 22050 : KOKORO_SR;
    const u = job.units.shift();
    if (u) {
      for (const c of await synth(u.voice, u.text, job)) job.chunks.push(job.gain === 1 ? c : Float32Array.from(c, (x) => x * job.gain));
      if (u.para) job.chunks.push(new Float32Array(Math.round(job.sr * Math.max(0, PARAGRAPH_PAUSE * (job.ppause ?? 1) - SENTENCE_PAUSE * (job.pause ?? 1)))));
    }
    postMessage({ type: "progress", id: -1 });
    if (queue.indexOf(job) < 0) { /* cancelado enquanto gerava */ }
    else if (!job.units.length) {
      queue.splice(queue.indexOf(job), 1);
      const data = wav(job.chunks, job.sr);
      postMessage({ type: "done", id: job.id, wav: data }, [data]);
    }
  } catch (e) {
    const k = queue.indexOf(job); if (k >= 0) queue.splice(k, 1);
    postMessage({ type: "error", id: job.id, message: String(e && e.message || e) });
  }
  busy = false;
  setTimeout(pump, 0);
}

onmessage = (e) => {
  const m = e.data;
  if (m.type === "speak") { queue.push(m); pump(); }
  else if (m.type === "cancel") {
    for (let i = queue.length - 1; i >= 0; i--) if (m.ids.includes(queue[i].id)) {
      postMessage({ type: "error", id: queue[i].id, message: "cancelado", cancelled: true }); queue.splice(i, 1);
    }
  } else if (m.type === "warm") {
    // baixa e carrega a voz e fala uma palavra em silêncio: o 1º play já sai rápido
    if (!queue.length && !busy) { busy = true; (async () => {
      try { await synth(m.voice || "pm_santa", "Olá.", { vocab: m.vocab, gpu: m.gpu, speed: 1, sr: 24000, expressiveness: 0.667 }); }
      catch (err) { postMessage({ type: "status", text: "" }); }
      busy = false; pump();
    })(); }
  }
};
