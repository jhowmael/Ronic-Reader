// Ronic Reader (iPad/iPhone): voz Kokoro rodando no próprio aparelho.
// Fonemas com o espeak-ng (WebAssembly) e modelo com o ONNX Runtime Web (GPU quando houver).
// Mesmo ajuste de sotaque do app do Mac: "y"->"i" e "æ"->"ɐ" (português do Brasil).
const PIPER = "https://cdn.jsdelivr.net/npm/@diffusionstudio/piper-wasm@1.0.0/build/piper_phonemize";
const ORT = "https://cdn.jsdelivr.net/npm/onnxruntime-web@1.22.0/dist/";
const HF = "https://huggingface.co/onnx-community/Kokoro-82M-v1.0-ONNX/resolve/main/";
const SR = 24000, SENTENCE_PAUSE = 0.18, PARAGRAPH_PAUSE = 0.45;

importScripts(PIPER + ".js", ORT + "ort.webgpu.min.js");
ort.env.wasm.wasmPaths = ORT;
// com isolamento (cabeçalhos do sw.js) o modelo roda em várias threads: 2-4x mais rápido
if (self.crossOriginIsolated) ort.env.wasm.numThreads = Math.max(1, Math.min(4, (self.navigator.hardwareConcurrency || 2) - 1));

let vocab = null, session = null, device = "wasm";
const styles = new Map();

async function init(vocabUrl) {
  if (session) return;
  vocab = await (await fetch(vocabUrl)).json();
  postMessage({ type: "status", text: "Baixando a voz (cerca de 90 MB, só na primeira vez)…" });
  const model = await (await fetch(HF + "onnx/model_quantized.onnx")).arrayBuffer();
  postMessage({ type: "status", text: "Carregando a voz…" });
  // GPU, senão CPU com threads, senão CPU simples; cada tentativa tem prazo para nunca travar
  const tries = [];
  if ("gpu" in self.navigator) tries.push(["webgpu", 0]);
  if (self.crossOriginIsolated) tries.push(["wasm", ort.env.wasm.numThreads]);
  tries.push(["wasm", 1]);
  for (const [ep, threads] of tries) {
    if (threads) ort.env.wasm.numThreads = threads;
    try {
      session = await Promise.race([ort.InferenceSession.create(model, { executionProviders: [ep] }),
        new Promise((_, no) => setTimeout(() => no(new Error("prazo")), 30000))]);
      device = ep; break;
    } catch (e) { session = null; }
  }
  if (!session) throw new Error("Não foi possível carregar a voz neste aparelho.");
  postMessage({ type: "ready", device });
}

async function voiceRows(name) {
  if (!styles.has(name)) {
    const buf = await (await fetch(HF + `voices/${name}.bin`)).arrayBuffer();
    styles.set(name, new Float32Array(buf));
  }
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

// espeak-ng é criado uma vez e reaproveitado
let phonemizer = null;
function phonemize(text) {
  return new Promise(async (resolve, reject) => {
    const run = (m) => {
      m._resolve = resolve;
      try { m.callMain(["-l", "pt-br", "--input", JSON.stringify([{ text }]), "--espeak_data", "/espeak-ng-data"]); }
      catch (e) { phonemizer = null; reject(e); }
    };
    if (!phonemizer) {
      const holder = {};
      phonemizer = await createPiperPhonemize({
        print: (d) => { try { const j = JSON.parse(d); holder.m._resolve(j.phonemes.flat().join("")); } catch (e) { /* linha extra */ } },
        printErr: () => {},
        locateFile: (u) => (u.endsWith(".wasm") ? PIPER + ".wasm" : u.endsWith(".data") ? PIPER + ".data" : u),
      });
      holder.m = phonemizer;
    }
    run(phonemizer);
  });
}
const ptbr = (ph) => ph.replace(/y/g, "i").replace(/æ/g, "ɐ");

async function speakPhonemes(ph, style, speed) {
  const ids = [...ph].map((c) => vocab[c]).filter((x) => x !== undefined).slice(0, 508);
  if (!ids.length) return new Float32Array(0);
  const row = Math.min(ids.length, 510) - 1;
  const feeds = {
    [session.inputNames[0]]: new ort.Tensor("int64", BigInt64Array.from([0, ...ids, 0].map(BigInt)), [1, ids.length + 2]),
    style: new ort.Tensor("float32", style.slice(row * 256, row * 256 + 256), [1, 256]),
    speed: new ort.Tensor("float32", Float32Array.from([speed]), [1]),
  };
  const r = await session.run(feeds);
  return r[session.outputNames[0]].data;
}
// frases do texto em fonemas, sem passar de ~250 símbolos por inferência
function phonemeSentences(ph) {
  const out = []; let cur = "";
  for (const piece of ph.split(/(?<=[.!?…])\s+/)) {
    if (cur && cur.length + piece.length > 250) { out.push(cur); cur = piece; }
    else cur = cur ? cur + " " + piece : piece;
  }
  if (cur) out.push(cur);
  return out;
}

function wav(chunks) {
  const total = chunks.reduce((n, c) => n + c.length, 0);
  const buf = new ArrayBuffer(44 + total * 2), v = new DataView(buf);
  const w = (o, s) => [...s].forEach((c, i) => v.setUint8(o + i, c.charCodeAt(0)));
  w(0, "RIFF"); v.setUint32(4, 36 + total * 2, true); w(8, "WAVE"); w(12, "fmt ");
  v.setUint32(16, 16, true); v.setUint16(20, 1, true); v.setUint16(22, 1, true); v.setUint32(24, SR, true);
  v.setUint32(28, SR * 2, true); v.setUint16(32, 2, true); v.setUint16(34, 16, true); w(36, "data"); v.setUint32(40, total * 2, true);
  let o = 44;
  for (const c of chunks) for (let i = 0; i < c.length; i++, o += 2) v.setInt16(o, Math.max(-1, Math.min(1, c[i])) * 32767, true);
  return buf;
}

// fila: cada pedido vira parágrafos; entre um parágrafo e outro, pedidos mais urgentes
// (a 1ª frase de um play) passam na frente da pré-geração que já começou.
const queue = []; let busy = false;
function units(job) {
  const out = [];
  for (const part of job.parts) for (const para of part.text.split("\n\n")) if (para.trim()) out.push({ voice: part.voice, text: para.trim() });
  return out;
}
async function pump() {
  if (busy || !queue.length) return;
  busy = true;
  queue.sort((a, b) => b.priority - a.priority || a.id - b.id);
  const job = queue[0];
  try {
    await init(job.vocab);
    job.units ||= units(job); job.chunks ||= [];
    const u = job.units.shift();
    if (u) {
      const style = await styleFor(u.voice);
      for (const s of phonemeSentences(ptbr(await phonemize(u.text)))) {
        job.chunks.push(Float32Array.from(await speakPhonemes(s, style, job.speed), (x) => x * job.gain));
        job.chunks.push(new Float32Array(Math.round(SR * SENTENCE_PAUSE)));
      }
      job.chunks.push(new Float32Array(Math.round(SR * (PARAGRAPH_PAUSE - SENTENCE_PAUSE))));
    }
    if (!job.units.length) {
      queue.splice(queue.indexOf(job), 1);
      const data = wav(job.chunks);
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
  else if (m.type === "cancel") { for (let i = queue.length - 1; i >= 0; i--) if (m.ids.includes(queue[i].id)) { postMessage({ type: "error", id: queue[i].id, message: "cancelado", cancelled: true }); queue.splice(i, 1); } }
  else if (m.type === "warm") init(m.vocab).catch((err) => postMessage({ type: "status", text: String(err) }));
};
