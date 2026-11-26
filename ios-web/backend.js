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
  const DEFAULT_SETTINGS = { engine: "kokoro", voice: "if_sara", rate: "+0%", volume: "+0%", pitch: "+0Hz", expressiveness: 0.667 };

  async function kv(key, fallback) { const s = await load("store"); return (await s.get("kv", key)) ?? fallback; }
  async function setKv(key, value) { const s = await load("store"); await s.put("kv", value, key); return value; }
  const settings = () => kv("settings", DEFAULT_SETTINGS);

  // livros abertos nesta sessão (com o texto já organizado)
  const books = new Map();

  // ------------------------------------------------------------------- voz
  let worker = null, jobSeq = 0;
  const pending = new Map();
  function tts() {
    if (!worker) {
      worker = new Worker(ENGINE + "tts-worker.js");
      worker.onmessage = (e) => {
        const m = e.data;
        if (m.type === "status") window.RonicBackend.onStatus?.(m.text);
        if (m.type === "ready") window.RonicBackend.onStatus?.("");
        const p = pending.get(m.id); if (!p) return;
        pending.delete(m.id);
        if (m.type === "done") p.resolve(new Blob([m.wav], { type: "audio/wav" }));
        else { const err = new Error(m.message); if (m.cancelled) err.status = 409; p.reject(err); }
      };
    }
    return worker;
  }
  function speak(parts, s, priority) {
    const id = ++jobSeq;
    return new Promise((resolve, reject) => {
      pending.set(id, { resolve, reject });
      tts().postMessage({ type: "speak", id, parts, priority, vocab: new URL(ENGINE + "vocab.json", location.href).href,
        speed: Math.min(2, Math.max(0.5, 1 + pct(s.rate) / 100)), gain: Math.min(2, Math.max(0.3, 1 + pct(s.volume) / 100)) });
    });
  }
  // cache de áudio desta sessão
  const audioCache = new Map();
  const MAX_AUDIO = 40;
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
    const cat = (await voicesJson()).filter((v) => v.engine === "kokoro");
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
    const voices = (await voicesJson()).filter((v) => v.engine === "kokoro");
    const v = voices.find((x) => x.id === s.voice);
    return { version: "web", platform: "web", voices, presets: PRESETS, settings: s,
      describe: `${v ? v.label : s.voice} | velocidade ${s.rate} | volume ${s.volume}`,
      recent: await recent(), prefs: await kv("prefs", {}) };
  }
  async function openBytes(bytes, name) {
    const s = await load("store"), text = await load("text"), fmt = await load("formats");
    const id = await s.fileId(bytes);
    const existing = await s.get("books", id);
    if (existing) return openStored(id);
    window.RonicBackend.onStatus?.("Organizando o texto…");
    const isEpub = new Uint8Array(bytes.slice(0, 2)).toString() === "80,75";
    const stem = name.replace(/\.(pdf|epub)$/i, "");
    let book, cover;
    if (isEpub) {
      const e = await fmt.readEpub(bytes);
      book = text.buildEpubBook({ id, name: stem, title: e.title, author: e.author, chapters: e.chapters });
      cover = e.cover || await fmt.typographicCover(book.title, book.author);
    } else {
      const p = await fmt.readPdf(bytes);
      book = text.buildPdfBook({ id, name: stem, pages: p.pages, outline: p.outline, aspect: p.aspect, title: p.title, author: p.author });
      cover = p.cover;
    }
    await s.put("files", bytes, id);
    await s.put("covers", cover, id);
    await s.put("books", { id, name: book.title || stem, book, position: 0, opened: Date.now() });
    await s.persist();
    books.set(id, book);
    return { book, position: 0 };
  }
  async function openStored(id) {
    const s = await load("store");
    const rec = await s.get("books", id);
    if (!rec) throw new Error("Livro não encontrado na biblioteca.");
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
      pool: (await voicesJson()).filter((v) => v.engine === "kokoro") };
  }

  // áudio de um trecho: "full", "head" (1ª frase) ou "tail" (resto)
  async function audio(bookId, i, part) {
    const book = books.get(bookId); if (!book) throw new Error("Livro não está aberto.");
    const s = await settings();
    const voice = await voiceFor(book, i, s);
    const key = (pt) => `${bookId}:${i}:${pt}:${voice}:${s.rate}:${s.volume}`;
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

  window.RonicBackend = { api, audio, onStatus: null };
  // ?demo=arquivo.pdf abre um livro de exemplo (usado nos testes e na página do GitHub)
  const demo = new URLSearchParams(location.search).get("demo");
  if (demo) window.addEventListener("load", () => setTimeout(async () => {
    const blob = await (await fetch(demo)).blob();
    window.openFile?.(new File([blob], demo.split("/").pop(), { type: blob.type }));
  }, 300));
  // mostra o andamento da primeira carga da voz
  window.RonicBackend.onStatus = (text) => { const s = document.getElementById("status"); if (s) s.textContent = text || ""; };

  // modo offline: guarda o app e a voz no aparelho
  // na 1ª visita a página ainda não passou pelo service worker: recarrega uma vez para ficar isolada
  if ("serviceWorker" in navigator) navigator.serviceWorker.register("sw.js").then(() => navigator.serviceWorker.ready).then(() => {
    if (!window.crossOriginIsolated && !sessionStorage.getItem("ronic-coi")) {
      sessionStorage.setItem("ronic-coi", "1"); location.reload();
    }
  }).catch(() => {});
})();
