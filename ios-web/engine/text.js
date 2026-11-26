// Ronic Reader (iPad/iPhone): texto do livro, igual ao app do Mac.
// Porte de ronic_reader/cleaner.py, splitter.py, player.load_book e narration.py.

const W = "[\\p{L}\\p{N}_]";                       // \w do Python, com acentos
const reW = (s, f = "") => new RegExp(s.replaceAll("\\w", W), f + "u");

// ------------------------------------------------------------------ limpeza
const PAGE_NUMBER_RE = /^\s*[-–—]?\s*(p[áa]g(ina)?\.?|page|p\.)?\s*(\d{1,4}|[ivxlcdm]{1,7})(\s*(de|of|\/)\s*\d{1,4})?\s*[-–—]?\s*$/i;
const PAGE_OF_RE = /\bp[áa]g(?:ina|\.)?\s*\d{1,4}\s*(?:de|\/|of)\s*\d{1,4}\b/i;
const TOC_LEADER_RE = /\s*(\.\s*){4,}\s*\d*\s*$/;
const URL_RE = /\b(https?:\/\/|www\.)\S+/gi;
const MULTISPACE = /[ \t]+/g;
export const SENTENCE_END_RE = /[.!?:;…]["'”’»)\]]*$/;
const HEADING_RE = /^(cap[íi]tulo|chapter|parte|part|se[çc][ãa]o|section|pr[óo]logo|ep[íi]logo|introdu[çc][ãa]o|conclus[ãa]o|pref[áa]cio|ap[êe]ndice)(?![\p{L}])/iu;
const EDGE_LINES = 6;
const isUpper = (c) => c && c === c.toUpperCase() && c !== c.toLowerCase();
const isLower = (c) => c && c === c.toLowerCase() && c !== c.toUpperCase();

function normalizeChars(t) {
  return t.normalize("NFKC").replace(/­/g, "").replace(/[  ]/g, " ").replace(/​/g, "")
    .replace(/\r\n?/g, "\n").replace(/\f/g, "\n").replace(/[\u0000-\u0008\u000b-\u001f\u007f-\u009f]/g, "");
}
const lineKey = (l) => l.trim().toLowerCase().replace(MULTISPACE, " ").replace(/\d+/g, "#");

function repeatedEdges(pagesLines) {
  if (pagesLines.length < 3) return new Set();
  const count = new Map();
  for (const lines of pagesLines) {
    const ne = lines.filter((l) => l.trim());
    const keys = new Set([...ne.slice(0, EDGE_LINES), ...ne.slice(-EDGE_LINES)].map(lineKey));
    for (const k of keys) count.set(k, (count.get(k) || 0) + 1);
  }
  const thr = Math.max(3, Math.floor(pagesLines.length * 0.4));
  return new Set([...count].filter(([k, n]) => n >= thr && k.replace(/[# ]/g, "")).map(([k]) => k));
}
function stripEdges(lines, repeated) {
  const noise = (l) => repeated.has(lineKey(l)) || PAGE_NUMBER_RE.test(l);
  const idx = lines.map((l, i) => (l.trim() ? i : -1)).filter((i) => i >= 0);
  const edge = new Set([...idx.slice(0, EDGE_LINES), ...idx.slice(-EDGE_LINES)]);
  return lines.filter((l, i) => !(edge.has(i) && noise(l))).filter((l) => !(PAGE_OF_RE.test(l) && l.trim().length <= 80));
}
export function looksLikeChapter(p) {
  const s = p.trim();
  return HEADING_RE.test(s) && s.length <= 80 && isUpper(s[0]) && s.split(/\s+/).length <= 12 && !/[,;]$/.test(s);
}
export function isHeading(line) {
  const s = line.trim();
  if (!s || s.length > 80) return false;
  if (looksLikeChapter(s)) return true;
  const letters = [...s].filter((c) => /\p{L}/u.test(c));
  return letters.length >= 4 && letters.every(isUpper) && !SENTENCE_END_RE.test(s);
}
function joinLines(lines, typical) {
  const paras = []; let cur = "", prevLen = 0;
  for (const raw of lines) {
    let line = raw.replace(MULTISPACE, " ").trim().replace(TOC_LEADER_RE, "");
    if (!line) { if (cur) { paras.push(cur); cur = ""; } continue; }
    if (isHeading(line)) { if (cur) paras.push(cur); paras.push(line); cur = ""; prevLen = 0; continue; }
    if (!cur) cur = line;
    else if (reW("\\w-$").test(cur) && isLower(line[0])) cur = cur.slice(0, -1) + line;
    else if (SENTENCE_END_RE.test(cur) && prevLen < typical * 0.8) { paras.push(cur); cur = line; }
    else cur = `${cur} ${line}`;
    prevLen = line.length;
  }
  if (cur) paras.push(cur);
  return paras.join("\n\n");
}
function typicalLength(pagesLines) {
  const L = pagesLines.flat().map((l) => l.trim().length).filter((n) => n > 15).sort((a, b) => a - b);
  if (!L.length) return 60;
  return L.length >= 4 ? L[Math.floor(L.length * 0.75)] : L[L.length - 1];
}
function polish(t) {
  t = t.replace(URL_RE, "").replace(/^[•·▪●◦■□➢►\-–]\s*/gm, "").replace(/\s+([,.;:!?])/g, "$1")
    .replace(/\[\d+(,\s*\d+)*\]/g, "").replace(MULTISPACE, " ");
  return t.split("\n\n").map((p) => p.trim()).filter(Boolean).join("\n\n");
}
export function cleanPages(pages) {
  let pl = pages.map((p) => normalizeChars(p.text).split("\n"));
  const rep = repeatedEdges(pl);
  pl = pl.map((l) => stripEdges(l, rep));
  const typ = typicalLength(pl);
  return pages.map((p, i) => ({ number: p.number, text: polish(joinLines(pl[i], typ)) }));
}
// (página, parágrafo), emendando frases que continuam na página seguinte
export function paragraphs(pages) {
  const out = [];
  for (const page of pages) {
    page.text.split("\n\n").filter((p) => p.trim()).forEach((para, i) => {
      if (i === 0 && out.length) {
        const [pp, prev] = out[out.length - 1];
        if (reW("\\w-$").test(prev) && isLower(para[0])) { out[out.length - 1] = [pp, prev.slice(0, -1) + para]; return; }
        if (!SENTENCE_END_RE.test(prev) && isLower(para[0])) { out[out.length - 1] = [pp, `${prev} ${para}`]; return; }
      }
      out.push([page.number, para]);
    });
  }
  return out;
}

// ------------------------------------------------------------------ frases
const SENT_SPLIT = /(?<=[.!?…])["'”’»)]*\s+/;
export const splitSentences = (t) => t.split(SENT_SPLIT).map((s) => s.trim()).filter(Boolean);
export function chunkText(text, max = 400) {
  const chunks = []; let buf = "";
  const push = (piece, sep) => {
    if (buf && buf.length + sep.length + piece.length > max) { chunks.push(buf); buf = piece; }
    else buf = buf ? buf + sep + piece : piece;
  };
  for (let para of text.split("\n\n")) {
    para = para.trim(); if (!para) continue;
    if (para.length <= max) { push(para, "\n\n"); continue; }
    for (let s of splitSentences(para)) {
      while (s.length > max) { let cut = s.lastIndexOf(" ", max); cut = cut > 0 ? cut : max; push(s.slice(0, cut), " "); s = s.slice(cut).trim(); }
      push(s, " ");
    }
  }
  if (buf) chunks.push(buf);
  return chunks;
}
// primeira frase (para tocar já) e o resto
export function splitHead(text, min = 25, max = 90) {
  const re = /[.!?…]["'”’»)]*\s+/g; let cut = null, m;
  while ((m = re.exec(text))) { if (m.index + m[0].length >= min) { cut = m.index + m[0].length; break; } }
  if (cut === null || cut > max) {
    if (text.length <= max) return [text, ""];
    const w = text.slice(0, max);
    cut = Math.max(w.lastIndexOf(", "), w.lastIndexOf("; ")) + 1 || w.lastIndexOf(" ");
    cut = cut > min ? cut : max;
  }
  return [text.slice(0, cut).trim(), text.slice(cut).trim()];
}

// ------------------------------------------------------------------ livro
const SEGMENT_CHARS = 400;
const NUMBERED = /^(\d{1,2})(\.\d{1,2})*\.?\s+[A-ZÀ-Ý]/;
const LOWER_WORDS = new Set("de da do das dos e em para a o as os com na no nas nos por à ao aos".split(" "));
const fold = (s) => s.normalize("NFKD").replace(/\p{M}/gu, "").toLowerCase();

function sectionKind(para) {
  const s = para.trim();
  if (s.length > 90 || s.includes("\n") || /[,;:]$/.test(s)) return null;
  if (looksLikeChapter(s)) return "chap";
  const m = NUMBERED.exec(s);
  if (m && s.split(/\s+/).length <= 12 && !/[.!?]$/.test(s.replace(/["”]+$/, ""))) return m[2] ? "sub" : "num";
  return isHeading(s) ? "caps" : null;
}
export function smartCase(t) {
  const letters = [...t].filter((c) => /\p{L}/u.test(c));
  if (!letters.length || letters.some(isLower)) return t;
  return t.toLowerCase().split(/\s+/).map((w, i) => (i && LOWER_WORDS.has(w) ? w : w[0].toUpperCase() + w.slice(1))).join(" ");
}
export function uninformativeName(n) {
  n = n.toLowerCase();
  return /^[0-9a-f_\-\s.]+$/.test(n) || !/\p{L}{3,}/u.test(n) || ["document", "documento", "arquivo", "file", "untitled"].includes(n);
}
function titleFromCover(heads) {
  const runs = [];
  for (const t of heads) {
    if (runs.length && /\b(DE|DA|DO|DAS|DOS|E|EM|PARA|A|O|AS|OS|COM|NA|NO)$/i.test(runs[runs.length - 1])) runs[runs.length - 1] += " " + t;
    else runs.push(t);
  }
  const good = runs.filter((r) => !/\b(LTDA|S\.?\/?A\.?|EIRELI|ME|INC|LLC)\b/i.test(r) && (r.match(/\p{L}/gu) || []).length >= 8);
  return good.length ? smartCase(good.reduce((a, b) => (b.length > a.length ? b : a))) : "";
}
// UTF-8 lido como PDFDocEncoding ("CÃ³digo" -> "Código"), como no app do Mac
const PDFDOC = new Map([..."\u02d818\u02c719\u02c61a\u02d91b\u02dd1c\u02db1d\u02da1e\u02dc1f\u202280\u202081\u202182\u202683\u201484\u201385\u019286\u204487\u203988\u203a89\u22128a\u20308b\u201e8c\u201c8d\u201d8e\u20188f\u201990\u201a91\u212292\ufb0193\ufb0294\u014195\u015296\u016097\u017898\u017d99\u01319a\u01429b\u01539c\u01619d\u017e9e\u20aca0".matchAll(/([\s\S])([0-9a-f]{2})/g)].map((m) => [m[1], parseInt(m[2], 16)]));
function fixMojibake(t) {
  if (!/[ÃÂ]/.test(t)) return t;
  const bytes = [...t].map((c) => PDFDOC.get(c) ?? (c.charCodeAt(0) < 256 ? c.charCodeAt(0) : 63));
  try { return new TextDecoder("utf-8", { fatal: true }).decode(new Uint8Array(bytes)); } catch (e) { return t; }
}
export function cleanTitle(raw) {
  let t = fixMojibake(String(raw || "").trim())
    .replace(/^(Microsoft (Word|PowerPoint)|Word|PowerPoint|Documentos? Google)\s*[-–:]\s*/i, "")
    .replace(/\.(docx?|odt|pages|rtf|pptx?|txt|pdf)$/i, "").trim();
  return /^(untitled|sem t[íi]tulo|documento\d*|document\d*|\W*)$/i.test(t) ? "" : t;
}

// Páginas do PDF já extraídas -> livro (mesma estrutura do app do Mac)
export function buildPdfBook({ id, name, pages, outline, aspect, title, author }) {
  const cleaned = cleanPages(pages);
  if (!pages.some((p) => p.text.trim().length >= 20)) throw new Error("Este PDF não tem texto selecionável (parece escaneado).");
  const nums = new Set(cleaned.map((p) => p.number));
  const chapterPages = new Map();
  if (outline.length) {
    const levels = [...new Set(outline.map((o) => o.level))].sort();
    const level = levels.find((lv) => outline.filter((o) => o.level === lv && nums.has(o.page)).length >= 2) ?? levels[0];
    for (const o of outline) if (o.level === level && nums.has(o.page) && !chapterPages.has(o.page)) chapterPages.set(o.page, o.title || `Página ${o.page}`);
  }
  const segments = [], outlineCh = [], cand = { chap: [], num: [], caps: [] }, coverHeads = [];
  const firstPage = cleaned.find((p) => p.text.trim())?.number ?? 1;
  let buf = "", bufPage = 0, bufCont = false; const seen = new Set();
  const flush = () => { if (buf) { segments.push({ page: bufPage, text: buf, cont: bufCont, heading: false, level: 0 }); buf = ""; } };
  for (const [page, para] of paragraphs(cleaned)) {
    if (buf && page !== bufPage) flush();
    if (chapterPages.has(page) && !seen.has(page)) { flush(); outlineCh.push({ title: chapterPages.get(page), segment: segments.length }); }
    seen.add(page);
    const kind = sectionKind(para);
    if (kind) {
      flush();
      if (cand[kind]) cand[kind].push({ title: smartCase(para), segment: segments.length });
      if (kind === "caps" && page === firstPage) coverHeads.push(para);
      segments.push({ page, text: para, cont: false, heading: true, level: kind === "num" || kind === "sub" ? 2 : 1 });
      continue;
    }
    chunkText(para, SEGMENT_CHARS).forEach((piece, k) => {
      if (buf && buf.length + piece.length > SEGMENT_CHARS) flush();
      if (!buf) { buf = piece; bufPage = page; bufCont = k > 0; }
      else buf = k > 0 ? `${buf} ${piece}` : `${buf}\n\n${piece}`;
    });
  }
  flush();
  let chapters;
  if (outlineCh.length) chapters = outlineCh;
  else {
    chapters = ["chap", "num"].map((k) => cand[k]).find((c) => c.length >= 2) || cand.caps;
    const norm = (t) => fold(t).replace(/\W+/g, "");
    const last = new Map(chapters.map((c, k) => [norm(c.title), k]));
    chapters = chapters.filter((c, k) => last.get(norm(c.title)) === k);
  }
  if (!chapters.length || chapters[0].segment > 0) chapters.unshift({ title: "Início", segment: 0 });
  let t = cleanTitle(title);
  if (!t && uninformativeName(name)) t = titleFromCover(coverHeads);
  return { id, name, total_pages: pages.length, aspect, title: t || name, author: author || "", format: "pdf", segments, chapters };
}

// EPUB (capítulos em blocos) -> livro com uma página por capítulo
export function buildEpubBook({ id, name, title, author, chapters: chs }) {
  const PAGE = Infinity, segments = [], chapters = [];   // um capítulo = uma página (texto corrido)
  let page = 0;
  chs.forEach((ch) => {
    // "I" + "Do título." -> "I — Do título"
    const blocks = [];
    for (let k = 0; k < ch.blocks.length; k++) {
      const b = ch.blocks[k], nx = ch.blocks[k + 1];
      if (b.kind === "h" && /^(?:[IVXLCDM]{1,7}|\d{1,4})\.?$/.test(b.text) && nx && nx.text.length <= 80) {
        blocks.push({ kind: "h", text: `${b.text} — ${nx.text.replace(/\.$/, "")}`, level: b.level || 2 }); k++;
      } else blocks.push(b);
    }
    page++; let used = 0, buf = "", bufPage = page;
    const flush = () => { if (buf) { segments.push({ page: bufPage, text: buf, cont: false, heading: false, level: 0 }); buf = ""; } };
    chapters.push({ title: ch.title, segment: segments.length });
    for (const b of blocks) {
      const size = b.text.length + 60;
      if (used && used + size > PAGE && b.kind === "p") { flush(); page++; used = 0; }
      used += size;
      if (b.kind === "h") { flush(); segments.push({ page, text: b.text, cont: false, heading: true, level: b.level <= 2 ? 1 : 2 }); continue; }
      chunkText(b.text, SEGMENT_CHARS).forEach((piece, k) => {
        if (buf && (buf.length + piece.length > SEGMENT_CHARS || bufPage !== page)) flush();
        if (!buf) { buf = piece; bufPage = page; if (k > 0) { segments.push({ page, text: piece, cont: true, heading: false, level: 0 }); buf = ""; } }
        else buf = k > 0 ? `${buf} ${piece}` : `${buf}\n\n${piece}`;
      });
    }
    flush();
  });
  if (!segments.length) throw new Error("Não encontrei texto neste EPUB.");
  return { id, name, total_pages: page, aspect: 0.66, title: title || name, author: author || "", format: "epub", segments, chapters };
}

// ------------------------------------------------------- narração por contexto
// Mesmas regras de ronic_reader/narration.py: capítulos de ponto de vista ("3 — Briana"),
// senão 1ª pessoa com gênero pela concordância, senão um narrador só.
const NB = "(?<![\\p{L}])", NE = "(?![\\p{L}])";
const FIRST_PERSON = new RegExp(`${NB}(eu|me|mim|meu|minha|meus|minhas|comigo)${NE}`, "giu");
const NARR_ADJ = new RegExp(`${NB}eu\\s+(?:estava|estou|era|sou|fui|fiquei|ficara|ficava|andava|vivia|me\\s+sentia|me\\s+senti|me\\s+achava|me\\s+achei|parecia|continuava|permaneci|seria|ficaria|estaria)\\s+(?:muito\\s+|tão\\s+|um\\s+pouco\\s+|meio\\s+)?(\\p{L}{4,}?)([oa]s?)${NE}`, "giu");
const FIXED_F = new RegExp(`${NB}(eu mesma|obrigada|sozinha|eu própria)${NE}`, "giu");
const FIXED_M = new RegExp(`${NB}(eu mesmo|obrigado|sozinho|eu próprio)${NE}`, "giu");
const TITLE_PREFIX = /^\s*(?:cap[íi]tulo|parte|chapter)?\s*(?:\d+|[IVXLCDM]+)?\s*[-–—:.·|]*\s*/i;
const PERSON_NAME = /^[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)?$/;
const MALE_A = new Set(["luca", "joshua", "elias", "jonas", "nicolas", "lucas", "thomas", "tomas", "andreas", "mattias"]);
const FEMALE_O = new Set(["rocio", "consuelo", "socorro", "amparo"]);
const NOT_NAMES = new Set(["início", "prólogo", "epílogo", "fim", "sobre"]);

export function chapterOf(book, i) {
  const st = book._starts ||= book.chapters.map((c) => c.segment);
  let lo = 0, hi = st.length - 1, n = 0;
  while (lo <= hi) { const m = (lo + hi) >> 1; if (st[m] <= i) { n = m; lo = m + 1; } else hi = m - 1; }
  return n;
}
const zero = () => ({ F: 0, M: 0, fp: 0, w: 0 });
const add = (a, b) => { for (const k in b) a[k] += b[k]; return a; };
function gender(v, name = "") {
  if (v.F !== v.M) return v.F > v.M ? "F" : "M";
  const n = name ? name.toLowerCase().split(/\s+/)[0] : "";
  if (n) {
    if (MALE_A.has(n) || (/(o|os|r|l|z|el)$/.test(n) && !FEMALE_O.has(n))) return "M";
    if (/[aey]$/.test(n) || FEMALE_O.has(n)) return "F";
  }
  return "?";
}
export function analyzeNarrators(book) {
  const per = {};
  book.segments.forEach((s, i) => {
    if (s.heading) return;
    const t = s.text.split("\n\n").filter((p) => !/^\s*[—–]/.test(p)).join("\n");
    const v = { F: (t.match(FIXED_F) || []).length, M: (t.match(FIXED_M) || []).length, fp: (t.match(FIRST_PERSON) || []).length, w: t.split(/\s+/).filter(Boolean).length };
    for (const m of t.matchAll(NARR_ADJ)) v[m[2].toLowerCase().startsWith("a") ? "F" : "M"]++;
    add(per[chapterOf(book, i)] ||= zero(), v);
  });
  const names = {}, counts = {};
  book.chapters.forEach((c, k) => {
    const rest = (c.title || "").replace(TITLE_PREFIX, "").trim();
    if (PERSON_NAME.test(rest) && !NOT_NAMES.has(rest.toLowerCase())) { names[k] = rest; counts[rest] = (counts[rest] || 0) + 1; }
  });
  const pov = Object.entries(names).filter(([, n]) => counts[n] >= 2);
  const narrators = {}, byChapter = {};
  if (new Set(pov.map(([, n]) => n)).size >= 2) {
    for (const [k, n] of pov) {
      const id = n.toLowerCase();
      const d = narrators[id] ||= { id, name: n, chapters: [], _v: zero() };
      d.chapters.push(+k); add(d._v, per[k] || zero()); byChapter[k] = id;
    }
    for (const d of Object.values(narrators)) { d.gender = gender(d._v, d.name); delete d._v; }
  } else {
    const total = Object.values(per).reduce(add, zero());
    const first = total.w > 0 && total.fp / total.w > 0.025;
    const base = first ? gender(total) : "?";
    book.chapters.forEach((c, k) => {
      const v = per[k] || zero();
      let g = base;
      if (first && v.w > 150 && Math.abs(v.F - v.M) >= 2) g = v.F > v.M ? "F" : "M";
      const id = g === "F" ? "narradora" : "narrador";
      const d = narrators[id] ||= { id, name: id === "narradora" ? "Narradora" : "Narrador", gender: g === "F" || g === "M" ? g : "?", chapters: [] };
      d.chapters.push(k); byChapter[k] = id;
    });
  }
  return { narrators: Object.values(narrators).sort((a, b) => b.chapters.length - a.chapters.length), by_chapter: byChapter };
}
