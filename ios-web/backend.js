// Ronic Reader (iPad/iPhone): o "servidor" do app rodando dentro do Safari.
// Responde às mesmas rotas que ronic_reader/server.py responde no Mac, então a interface
// (ronic_reader/web/index.html) é a mesma nos dois. Tudo fica no aparelho: livros no
// IndexedDB, voz Kokoro num Web Worker, nada é enviado a servidores.
(function () {
  "use strict";
  const ENGINE = "./engine/";
  const mods = {};
  const load = (name) => (mods[name] ||= import(ENGINE + name + ".js"));
  let catalog = null;
  const voicesJson = () => (catalog ||= fetch(ENGINE + "voices.json").then((r) => r.json())
    .then((list) => list.map((v) => ({ ...v, group: (v.group || "").replace("no seu Mac", "no aparelho") }))));

  // ----------------------------------------------------------------- utilidades
  const PRESETS = [
    { id: "natural", rate: "+0%", volume: "+0%", pitch: "+0Hz", expressiveness: 0.667, desc: "neutro" },
    { id: "narrador", rate: "-5%", volume: "+0%", pitch: "-2Hz", expressiveness: 0.75, desc: "um pouco mais pausado" },
    { id: "calmo", rate: "-12%", volume: "-5%", pitch: "-4Hz", expressiveness: 0.5, desc: "lento e suave" },
    { id: "dinamico", rate: "+12%", volume: "+5%", pitch: "+3Hz", expressiveness: 0.85, desc: "mais rápido e animado" },
    { id: "estudo", rate: "+30%", volume: "+0%", pitch: "+0Hz", expressiveness: 0.6, desc: "bem rápido, para revisar" },
  ];
  const pct = (s) => parseInt(String(s || "0").replace(/[^\d+-]/g, ""), 10) || 0;
  const MOBILE = /iPhone|iPad|Android|Mobile/.test(navigator.userAgent) || (navigator.platform === "MacIntel" && navigator.maxTouchPoints > 1);
  // Na web só vozes sem sotaque: o Santa (voz brasileira nativa do Kokoro) e as vozes pt-BR do próprio aparelho
  const SANTA = "pm_santa";
  const DEFAULT_SETTINGS = { engine: "kokoro", voice: SANTA, rate: "+0%", volume: "+0%", pitch: "+0Hz", expressiveness: 0.667, pause: 1 };
  async function kv(key, fallback) { const s = await load("store"); return (await s.get("kv", key)) ?? fallback; }
  async function setKv(key, value) { const s = await load("store"); await s.put("kv", value, key); return value; }
  async function settings() {
    const s = { ...DEFAULT_SETTINGS, ...(await kv("settings", DEFAULT_SETTINGS)) };
    // voz que saiu da lista (com sotaque, ou Piper): volta para o Santa
    if (!s.voice.startsWith("sys:") && s.voice !== SANTA) return setKv("settings", { ...s, engine: "kokoro", voice: SANTA });
    return s;
  }

  // livros abertos nesta sessão (com o texto já organizado)
  const books = new Map();

  // ------------------------------------------------------------------- voz
  // O modelo roda num Worker. Se ele cair (o iPhone mata processos que usam muita memória) ou
  // parar de responder, os pedidos falham com erro em vez de ficar "Preparando a voz…" para sempre,
  // e o próximo pedido cria um Worker novo.
  let worker = null, jobSeq = 0, lastActivity = 0, phase = "idle";
  const pending = new Map();
  const gpuOk = () => { try { return localStorage.getItem("ronic-nogpu") !== "1"; } catch (e) { return true; } };
  let gpuLoading = false;
  function resetWorker(message) {
    if (gpuLoading || phase === "load" || phase === "download") { try { localStorage.setItem("ronic-nogpu", "1"); } catch (e) {} }
    if (worker) { try { worker.terminate(); } catch (e) {} }
    worker = null; phase = "idle";
    for (const [, p] of pending) { const err = new Error(message); err.retry = true; p.reject(err); }
    pending.clear(); audioCache.clear();
    window.RonicBackend.onStatus?.("");
  }
  setInterval(() => {
    if (!worker || !pending.size) return;
    const limit = phase === "download" ? 90000 : phase === "load" ? 25000 : 45000;
    if (Date.now() - lastActivity > limit) resetWorker("A voz parou de responder e foi reiniciada.");
  }, 3000);
  function tts() {
    if (!worker) {
      worker = new Worker(ENGINE + "tts-worker.js");
      lastActivity = Date.now();
      worker.onerror = (e) => { e.preventDefault?.(); resetWorker("A voz deste aparelho falhou e foi reiniciada."); };
      worker.onmessage = (e) => {
        const m = e.data; lastActivity = Date.now();
        if (m.type === "status") { phase = m.phase || phase; if (m.phase) gpuLoading = gpuOk(); window.RonicBackend.onStatus?.(m.text); }
        if (m.type === "ready") { phase = "run"; gpuLoading = false; window.RonicBackend.onStatus?.(""); }
        if (m.type === "progress") return;
        const p = pending.get(m.id); if (!p) return;
        pending.delete(m.id);
        if (m.type === "done") p.resolve(new Blob([m.wav], { type: "audio/wav" }));
        else { const err = new Error(m.message); if (m.cancelled) err.status = 409; p.reject(err); }
      };
    }
    return worker;
  }
  const jobSeg = new Map();   // job -> [livro, trecho], para cancelar o que ficou longe da leitura
  function speak(parts, s, priority, where) {
    const id = ++jobSeq;
    if (where) jobSeg.set(id, where);
    return new Promise((resolve, reject) => {
      if (!pending.size) lastActivity = Date.now();
      pending.set(id, { resolve: (v) => { jobSeg.delete(id); resolve(v); }, reject: (e) => { jobSeg.delete(id); reject(e); } });
      tts().postMessage({ type: "speak", id, parts, priority, vocab: new URL(ENGINE + "vocab.json", location.href).href,
        speed: Math.min(2, Math.max(0.5, 1 + pct(s.rate) / 100)), gain: Math.min(2, Math.max(0.3, 1 + pct(s.volume) / 100)),
        gpu: gpuOk(), expressiveness: s.expressiveness ?? 0.667, pitch: Math.pow(2, pct(s.pitch) / 120), pause: s.pause ?? 1, ppause: s.ppause ?? 1 });
    });
  }
  // aquece a voz (baixa e carrega o modelo) sem gerar nada: chamado ao abrir um livro
  async function warm() {
    const s = await settings();
    if (s.engine !== "kokoro") return;
    lastActivity = Date.now();
    tts().postMessage({ type: "warm", vocab: new URL(ENGINE + "vocab.json", location.href).href, voice: s.voice, gpu: gpuOk() });
  }

  // ------------------------------------------------ vozes do sistema (iOS, macOS, Android)
  // Instantâneas e sem download: o próprio aparelho fala (speechSynthesis).
  function systemVoices() {
    if (!("speechSynthesis" in window)) return [];
    // só sotaque do Brasil
    // vozes de brincadeira do macOS/iOS (Grandma, Rocko, Zarvox…) ficam de fora
    const JOKE = /\b(eddy|flo|grand(ma|pa)|reed|rocko|sandy|shelley|albert|bad news|bahh|bells|boing|bubbles|cellos|fred|good news|jester|junior|kathy|organ|ralph|superstar|trinoids|whisper|wobble|zarvox)\b/i;
    const list = speechSynthesis.getVoices().filter((v) => /^pt[-_]BR$/i.test(v.lang) && !JOKE.test(v.name));
    const br = (v) => /BR/i.test(v.lang);
    const FEM = /luciana|joana|catarina|fernanda|francisca|helena|maria|vit[oó]ria|camila|let[ií]cia|thalita|raquel|female|feminina/i;
    const MAS = /felipe|daniel|ant[oô]nio|duarte|jo[aã]o|ricardo|male|masculina/i;
    return list.sort((a, b) => br(b) - br(a) || (b.localService - a.localService)).map((v) => {
      const quality = /premium|enhanced|aprimorad|natural|neural/i.test(v.name) ? "alta qualidade" : "padrão";
      const label = v.name.replace(/\s*\((?:Enhanced|Premium|Aprimorada?|português.*)\)\s*$/i, "").replace(/^Microsoft\s+|\s+Online.*$/g, "")
        .replace(/^Google português do Brasil$/i, "Google").split(/\s[-–]\s/)[0];
      const g = FEM.test(v.name) ? "F" : MAS.test(v.name) ? "M" : "?";
      return { id: "sys:" + v.voiceURI, label, gender: g, engine: "system",
        desc: `${g === "F" ? "feminina · " : g === "M" ? "masculina · " : ""}${quality}`,
        group: "Brasil · voz do aparelho, instantânea", region: "Brasil" };
    });
  }
  if ("speechSynthesis" in window) speechSynthesis.addEventListener?.("voiceschanged", () => window.refreshState?.());
  const allVoices = async () => [
    ...(await voicesJson()).filter((v) => v.id === SANTA).map((v) => ({ ...v, desc: "masculina · natural, sem internet", group: "Brasil · sem internet" })),
    ...systemVoices()];

  // cache de áudio desta sessão
  const audioCache = new Map();
  const MAX_AUDIO = 160;
  function remember(key, promise) {
    audioCache.set(key, promise);
    promise.catch(() => audioCache.delete(key));
    if (audioCache.size > MAX_AUDIO) audioCache.delete(audioCache.keys().next().value);
    return promise;
  }

  // ------------------------------------------------- narração por contexto
  async function narrationData(book) {
    const d = await kv("narration:" + book.id, null);
    if (d && d.version === 2) return d;
    const { analyzeNarrators } = await load("text");
    return setKv("narration:" + book.id, { version: 2, enabled: !!d?.enabled, voices: {}, analysis: analyzeNarrators(book) });
  }
  // voz de cada narrador: escolha da pessoa, senão a principal (mesmo gênero), senão outra do gênero sem repetir
  async function narratorVoices(d, main) {
    const all = await allVoices();
    const engine = all.find((v) => v.id === main)?.engine || "kokoro";
    const cat = all.filter((v) => v.engine === engine);
    const mainG = cat.find((v) => v.id === main)?.gender;
    const out = {}, used = new Set();
    for (const n of d.analysis.narrators) {
      const chosen = d.voices[n.id];
      if (chosen && cat.some((v) => v.id === chosen)) out[n.id] = chosen;
      else if (!used.has(main) && (n.gender === mainG || n.gender === "?")) out[n.id] = main;
      else {
        const pool = cat.filter((v) => v.gender === n.gender).map((v) => v.id);
        out[n.id] = pool.find((v) => !used.has(v) && v !== main) || pool[0] || main;
      }
      used.add(out[n.id]);
    }
    return out;
  }
  async function voiceFor(book, i, s) {
    const d = await narrationData(book);
    if (!d.enabled) return s.voice;
    const { chapterOf } = await load("text");
    const id = d.analysis.by_chapter[chapterOf(book, i)];
    return (id && (await narratorVoices(d, s.voice))[id]) || s.voice;
  }

  // ------------------------------------------------------------- biblioteca
  async function recent() {
    const s = await load("store");
    return (await s.all("books")).map((b) => ({ id: b.id, name: b.custom_name || b.name, position: b.position || 0, page: b.page,
      segments: b.book.segments.length, total_pages: b.book.total_pages, format: b.book.format, opened: b.opened,
      custom_cover: !!b.custom_cover, cover_v: b.cover_v || 0 })).sort((a, b) => b.opened - a.opened);
  }
  async function state() {
    const s = await settings();
    const voices = await allVoices();
    const v = voices.find((x) => x.id === s.voice);
    return { version: "web", platform: "web", voices, presets: PRESETS, settings: s,
      describe: `${v ? v.label : s.voice} | velocidade ${s.rate} | volume ${s.volume}`,
      recent: await recent(), prefs: await kv("prefs", {}) };
  }
  // versão da leitura do texto: livros guardados com uma versão antiga são relidos do arquivo
  const PARSER = 4;
  async function parse(bytes, stem, id) {
    const text = await load("text"), fmt = await load("formats");
    const isEpub = new Uint8Array(bytes.slice(0, 2)).toString() === "80,75";
    if (isEpub) {
      const e = await fmt.readEpub(bytes);
      const book = text.buildEpubBook({ id, name: stem, title: e.title, author: e.author, chapters: e.chapters });
      return { book, cover: e.cover || await fmt.typographicCover(book.title, book.author) };
    }
    const p = await fmt.readPdf(bytes);
    return { book: text.buildPdfBook({ id, name: stem, pages: p.pages, outline: p.outline, aspect: p.aspect, title: p.title, author: p.author }), cover: p.cover };
  }
  async function openBytes(bytes, name) {
    const s = await load("store");
    const id = await s.fileId(bytes);
    if (await s.get("books", id)) return openStored(id);
    window.RonicBackend.onStatus?.("Organizando o texto…");
    const stem = name.replace(/\.(pdf|epub)$/i, "");
    const { book, cover } = await parse(bytes, stem, id);
    await s.put("files", bytes, id);
    await s.put("covers", cover, id);
    await s.put("books", { id, name: book.title || stem, book, parser: PARSER, position: 0, opened: Date.now() });
    await s.persist();
    books.set(id, book);
    window.RonicBackend.onStatus?.("");
    return { book, position: 0 };
  }
  async function openStored(id) {
    const s = await load("store");
    const rec = await s.get("books", id);
    if (!rec) throw new Error("Livro não encontrado na biblioteca.");
    if (rec.parser !== PARSER) {   // relê com as regras novas, mantendo o lugar aproximado da leitura
      const bytes = await s.get("files", id);
      if (bytes) {
        const old = rec.book, frac = (rec.position || 0) / Math.max(1, old.segments.length - 1);
        rec.book = (await parse(bytes, rec.book.name || rec.name, id)).book;
        rec.position = Math.round(frac * (rec.book.segments.length - 1)); rec.parser = PARSER;
        await s.del("kv", "narration:" + id);
      }
    }
    rec.opened = Date.now(); await s.put("books", rec);
    const book = { ...rec.book, title: rec.custom_name || rec.book.title };
    books.set(id, book);
    return { book, position: Math.min(rec.position || 0, book.segments.length - 1) };
  }
  async function updateBook(id, fn) {
    const s = await load("store"); const rec = await s.get("books", id);
    if (!rec) throw new Error("Livro não encontrado na biblioteca.");
    await fn(rec, s); await s.put("books", rec);
  }

  // ----------------------------------------------------------------- rotas
  async function api(path, { method = "GET", json, body } = {}) {
    const url = new URL(path, location.href);
    const p = url.pathname.replace(/^.*\/api\//, "/api/");
    const parts = p.split("/").filter(Boolean);
    if (p === "/api/state") return state();
    if (p === "/api/settings") { await setKv("settings", { ...(await settings()), ...json }); audioCache.clear(); return state(); }
    if (p === "/api/prefs") return setKv("prefs", { ...(await kv("prefs", {})), ...json });
    if (p === "/api/open") return openBytes(await body.arrayBuffer(), url.searchParams.get("name") || "livro.pdf");
    if (p === "/api/open_recent") return openStored(json.id);
    if (p === "/api/remove_recent") {
      const s = await load("store");
      await Promise.all([s.del("books", json.id), s.del("files", json.id), s.del("covers", json.id), s.del("kv", "narration:" + json.id)]);
      return { ok: true };
    }
    if (p === "/api/position") { await updateBook(json.id, (r) => { r.position = json.position; r.page = json.page; }); return { ok: true }; }
    if (p === "/api/library/rename") {
      await updateBook(json.id, (r) => { r.custom_name = (json.name || "").trim() || undefined; });
      const b = books.get(json.id); if (b) b.title = json.name || b.title;
      return state();
    }
    if (p === "/api/library/cover" || p === "/api/library/cover_upload") {
      const id = json?.id || url.searchParams.get("id");
      await updateBook(id, async (r, s) => {
        if (json?.reset) {
          const fmt = await load("formats");
          const bytes = await s.get("files", id);
          const isEpub = new Uint8Array(bytes.slice(0, 2)).toString() === "80,75";
          const cover = isEpub ? ((await fmt.readEpub(bytes)).cover || await fmt.typographicCover(r.book.title, r.book.author))
            : await fmt.renderPdfPage(bytes, 1, 360);
          await s.put("covers", cover, id); r.custom_cover = false;
        } else if (json?.page) {
          const fmt = await load("formats");
          await s.put("covers", await fmt.renderPdfPage(await s.get("files", id), json.page), id); r.custom_cover = true;
        } else { await s.put("covers", body, id); r.custom_cover = true; }
        r.cover_v = (r.cover_v || 0) + 1;
      });
      return state();
    }
    if (parts[1] === "cover") { const s = await load("store"); const c = await s.get("covers", parts[2]); if (!c) throw new Error("sem capa"); return c; }
    if (parts[1] === "narration" && parts[2]) {
      const book = books.get(parts[2]); if (!book) throw new Error("Abra o livro primeiro.");
      return narrationState(book);
    }
    if (p === "/api/narration") {
      const book = books.get(json.id); if (!book) throw new Error("Abra o livro primeiro.");
      const d = await narrationData(book);
      if ("enabled" in json) d.enabled = !!json.enabled;
      for (const [id, v] of Object.entries(json.voices || {})) if (v) d.voices[id] = v;
      await setKv("narration:" + book.id, d);
      return narrationState(book);
    }
    if (p === "/api/prepare_voice" || p === "/api/reveal") return { ok: true };
    throw new Error("Não disponível no iPad: " + p);
  }
  async function narrationState(book) {
    const s = await settings(), d = await narrationData(book);
    return { enabled: d.enabled, narrators: d.analysis.narrators, voices: await narratorVoices(d, s.voice),
      pool: await (async () => { const all = await allVoices(); const eng = all.find((v) => v.id === s.voice)?.engine || "kokoro"; return all.filter((v) => v.engine === eng); })() };
  }

  // leitura em fila: o que está perto da posição atual vem primeiro; o que ficou para trás sai da fila
  let focusAt = 0;
  function focus(bookId, i) {
    focusAt = i;
    const ids = [...jobSeg].filter(([, [b, j]]) => b !== bookId || j < i || j > i + 3).map(([id]) => id);
    if (ids.length && worker) worker.postMessage({ type: "cancel", ids });
  }
  async function chunksOf(book, i) {
    const { speechChunks } = await load("text");
    book._chunks ||= new Map();
    if (!book._chunks.has(i)) book._chunks.set(i, speechChunks(book.segments[i].text));
    return book._chunks.get(i);
  }
  async function chunkCount(bookId, i) { const book = books.get(bookId); return book ? (await chunksOf(book, i)).length : 0; }

  // áudio de um trecho: "s<k>" (pedaço k, usado no iPhone/iPad), "full", "head" (1ª frase) ou "tail" (resto)
  async function audio(bookId, i, part) {
    const book = books.get(bookId); if (!book) throw new Error("Livro não está aberto.");
    const s = await settings();
    const voice = await voiceFor(book, i, s);
    if (voice.startsWith("sys:")) return { speech: { text: book.segments[i].text, voice: voice.slice(4), pitch: pct(s.pitch), volume: pct(s.volume) }, served: "full" };
    const key = (pt) => `${bookId}:${i}:${pt}:${voice}:${s.rate}:${s.volume}:${s.pitch}:${s.pause}:${s.ppause}`;
    if (/^s\d+$/.test(part)) {
      if (!audioCache.has(key(part))) {
        const c = (await chunksOf(book, i))[+part.slice(1)];
        const priority = 10 - Math.max(0, Math.min(9, i - focusAt));
        remember(key(part), c ? speak([{ voice, text: c.text, end: c.end }], s, priority, [bookId, i]) : Promise.resolve(new Blob([], { type: "audio/wav" })));
      }
      const blob = await audioCache.get(key(part));
      return { url: blob.size ? URL.createObjectURL(blob) : null, served: part };
    }
    if (part === "head" && audioCache.has(key("full"))) return { url: URL.createObjectURL(await audioCache.get(key("full"))), served: "full" };
    if (!audioCache.has(key(part))) {
      const { splitHead } = await load("text");
      const text = book.segments[i].text;
      const [head, tail] = splitHead(text);
      const t = part === "full" ? text : part === "head" ? head : tail;
      remember(key(part), t ? speak([{ voice, text: t }], s, part === "full" ? 0 : 1) : Promise.resolve(new Blob([], { type: "audio/wav" })));
    }
    const blob = await audioCache.get(key(part));
    return { url: blob.size ? URL.createObjectURL(blob) : null, served: part };
  }

  window.RonicBackend = { api, audio, warm, focus, chunkCount, onStatus: null };
  // ?demo=arquivo.pdf abre um livro de exemplo (usado nos testes e na página do GitHub)
  const demo = new URLSearchParams(location.search).get("demo");
  if (demo) window.addEventListener("load", () => setTimeout(async () => {
    const blob = await (await fetch(demo)).blob();
    window.openFile?.(new File([blob], demo.split("/").pop(), { type: blob.type }));
  }, 300));
  // mostra o andamento da primeira carga da voz
  // andamento da voz (baixando/carregando); ao terminar, volta para "Preparando a voz…" se ainda falta o 1º áudio
  window.RonicBackend.onStatus = (text) => {
    const el = document.getElementById("status"); if (!el) return;
    if (text) el.textContent = text;
    else if (/Baixando|Carregando/.test(el.textContent)) el.textContent = window.waitingVoice ? "Preparando a voz…" : "";
  };

  // modo offline: guarda o app e a voz no aparelho
  // na 1ª visita a página ainda não passou pelo service worker: recarrega uma vez para ficar isolada
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").then(() => navigator.serviceWorker.ready).then(() => {
    if (!window.crossOriginIsolated && !sessionStorage.getItem("ronic-coi")) {
      sessionStorage.setItem("ronic-coi", "1"); location.reload();
    }
  }).catch(() => {});
})();
