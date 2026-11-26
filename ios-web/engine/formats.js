// Ronic Reader (iPad/iPhone): leitura de PDF (PDF.js) e EPUB (JSZip), no próprio aparelho.
const PDFJS = "https://cdn.jsdelivr.net/npm/pdfjs-dist@4.10.38/build/";
const JSZIP = "https://cdn.jsdelivr.net/npm/jszip@3.10.1/dist/jszip.min.js";

let pdfjsPromise = null;
async function pdfjs() {
  if (!pdfjsPromise) pdfjsPromise = import(PDFJS + "pdf.min.mjs").then((m) => {
    m.GlobalWorkerOptions.workerSrc = PDFJS + "pdf.worker.min.mjs";
    return m;
  });
  return pdfjsPromise;
}

// ----------------------------------------------------------------------- PDF
export async function readPdf(bytes) {
  const lib = await pdfjs();
  const doc = await lib.getDocument({ data: bytes.slice(0), isEvalSupported: false }).promise;
  const pages = [];
  for (let n = 1; n <= doc.numPages; n++) {
    const page = await doc.getPage(n);
    const tc = await page.getTextContent();
    // linhas pela posição vertical; espaço maior entre linhas = parágrafo novo
    const lines = []; let cur = "", lastY = null, gaps = [];
    for (const it of tc.items) {
      if (!("str" in it)) continue;
      const y = it.transform[5];
      if (lastY !== null && Math.abs(y - lastY) > 2 && cur) { lines.push({ text: cur, y: lastY }); cur = ""; }
      cur += it.str;
      if (it.hasEOL) { lines.push({ text: cur, y }); cur = ""; lastY = null; continue; }
      lastY = y;
    }
    if (cur) lines.push({ text: cur, y: lastY });
    for (let i = 1; i < lines.length; i++) gaps.push(Math.abs(lines[i - 1].y - lines[i].y));
    const typical = gaps.length ? gaps.slice().sort((a, b) => a - b)[Math.floor(gaps.length / 2)] : 0;
    const out = [];
    lines.forEach((l, i) => {
      if (i && typical && Math.abs(lines[i - 1].y - l.y) > typical * 1.6) out.push("");
      out.push(l.text);
    });
    pages.push({ number: n, text: out.join("\n") });
    page.cleanup();
  }
  // sumário (bookmarks)
  const outline = [];
  try {
    const walk = async (items, level) => {
      for (const it of items || []) {
        try {
          const dest = typeof it.dest === "string" ? await doc.getDestination(it.dest) : it.dest;
          if (dest) outline.push({ title: (it.title || "").trim(), page: (await doc.getPageIndex(dest[0])) + 1, level });
        } catch (e) { /* item sem destino */ }
        await walk(it.items, level + 1);
      }
    };
    await walk(await doc.getOutline(), 0);
  } catch (e) { /* sem sumário */ }
  const first = await doc.getPage(1);
  const vp = first.getViewport({ scale: 1 });
  const meta = await doc.getMetadata().catch(() => ({}));
  const cover = await renderPage(doc, 1, 360);
  await doc.destroy();
  return { pages, outline, aspect: Math.min(1.6, Math.max(0.45, vp.width / vp.height)),
    title: meta?.info?.Title || "", author: meta?.info?.Author || "", cover };
}

async function renderPage(doc, n, width) {
  const page = await doc.getPage(n);
  const vp1 = page.getViewport({ scale: 1 });
  const vp = page.getViewport({ scale: width / vp1.width });
  const canvas = document.createElement("canvas");
  canvas.width = Math.round(vp.width); canvas.height = Math.round(vp.height);
  const ctx = canvas.getContext("2d");
  ctx.fillStyle = "#fff"; ctx.fillRect(0, 0, canvas.width, canvas.height);
  await page.render({ canvasContext: ctx, viewport: vp }).promise;
  return await new Promise((r) => canvas.toBlob(r, "image/jpeg", 0.85));
}

export async function renderPdfPage(bytes, n, width = 600) {
  const lib = await pdfjs();
  const doc = await lib.getDocument({ data: bytes.slice(0), isEvalSupported: false }).promise;
  try { return await renderPage(doc, Math.max(1, Math.min(n, doc.numPages)), width); }
  finally { await doc.destroy(); }
}

// ---------------------------------------------------------------------- EPUB
let zipPromise = null;
function jszip() {
  if (!zipPromise) zipPromise = new Promise((resolve, reject) => {
    if (window.JSZip) return resolve(window.JSZip);
    const s = document.createElement("script"); s.src = JSZIP;
    s.onload = () => resolve(window.JSZip); s.onerror = reject; document.head.appendChild(s);
  });
  return zipPromise;
}
const dirOf = (p) => p.includes("/") ? p.slice(0, p.lastIndexOf("/") + 1) : "";
function resolvePath(base, href) {
  const parts = (base + href.split("#")[0]).split("/"); const out = [];
  for (const p of parts) { if (p === "..") out.pop(); else if (p && p !== ".") out.push(p); }
  return decodeURIComponent(out.join("/"));
}
const BLOCK = new Set(["p", "div", "li", "blockquote", "pre", "dd", "dt", "td", "figcaption", "section", "article", "aside", "tr"]);
const HEAD = /^h([1-6])$/;
const SKIP = new Set(["script", "style", "head", "nav", "svg", "math", "rt", "rp"]);

function blocksOf(doc) {
  const blocks = []; let buf = "", level = 0;
  const flush = () => { const t = buf.replace(/\s+/g, " ").trim(); buf = ""; if (t) blocks.push({ kind: level ? "h" : "p", text: t.normalize("NFKC"), level }); };
  const walk = (node) => {
    for (const n of node.childNodes) {
      if (n.nodeType === 3) { buf += n.nodeValue; continue; }
      if (n.nodeType !== 1) continue;
      const tag = n.localName.toLowerCase();
      if (SKIP.has(tag)) continue;
      const h = HEAD.exec(tag);
      if (h) { flush(); level = +h[1]; walk(n); flush(); level = 0; continue; }
      if (tag === "br") { buf += " "; continue; }
      if (tag === "img") { const alt = (n.getAttribute("alt") || "").trim(); if (alt.length > 3 && !/\b(logo|ícone|icon|capa|cover)\b/i.test(alt)) buf += ` ${alt} `; continue; }
      if (BLOCK.has(tag)) { flush(); walk(n); flush(); } else walk(n);
    }
  };
  if (doc.body) walk(doc.body);
  flush();
  return blocks;
}

export async function readEpub(bytes) {
  const JSZip = await jszip();
  const zip = await JSZip.loadAsync(bytes);
  const xml = async (p) => new DOMParser().parseFromString(await zip.file(p).async("string"), "application/xml");
  const container = await xml("META-INF/container.xml");
  const opfPath = container.querySelector("rootfile").getAttribute("full-path");
  const base = dirOf(opfPath);
  const opf = await xml(opfPath);
  const text = (sel) => opf.getElementsByTagNameNS("*", sel)[0]?.textContent?.trim() || "";
  const manifest = {};
  for (const it of opf.getElementsByTagNameNS("*", "item"))
    manifest[it.getAttribute("id")] = { path: resolvePath(base, it.getAttribute("href")), media: it.getAttribute("media-type") || "", props: it.getAttribute("properties") || "" };
  const spine = [...opf.getElementsByTagNameNS("*", "itemref")].filter((r) => r.getAttribute("linear") !== "no").map((r) => r.getAttribute("idref"));

  // títulos do sumário
  const toc = {};
  const nav = Object.values(manifest).find((m) => m.props.split(" ").includes("nav"));
  if (nav && zip.file(nav.path)) {
    const d = new DOMParser().parseFromString(await zip.file(nav.path).async("string"), "application/xhtml+xml");
    for (const a of d.getElementsByTagName("a")) {
      const href = a.getAttribute("href"); if (!href) continue;
      const p = resolvePath(dirOf(nav.path), href); const t = a.textContent.replace(/\s+/g, " ").trim();
      if (t && !toc[p]) toc[p] = t;
    }
  }
  // capa
  let cover = null;
  const coverMeta = [...opf.getElementsByTagNameNS("*", "meta")].find((m) => m.getAttribute("name") === "cover")?.getAttribute("content");
  const coverItem = Object.values(manifest).find((m) => m.props.split(" ").includes("cover-image"))
    || (coverMeta && manifest[coverMeta]?.media.startsWith("image/") ? manifest[coverMeta] : null);
  if (coverItem && zip.file(coverItem.path)) cover = new Blob([await zip.file(coverItem.path).async("uint8array")], { type: coverItem.media });

  const chapters = [];
  for (const id of spine) {
    const it = manifest[id];
    if (!it || !it.media.includes("html") || !zip.file(it.path)) continue;
    const d = new DOMParser().parseFromString(await zip.file(it.path).async("string"), "text/html");
    const blocks = blocksOf(d);
    if (!blocks.some((b) => b.text.length > 1)) continue;
    chapters.push({ title: toc[it.path] || blocks.find((b) => b.kind === "h")?.text || `Parte ${chapters.length + 1}`, blocks });
  }
  if (!chapters.length) throw new Error("Não encontrei texto neste EPUB.");
  return { title: text("title"), author: text("creator"), chapters, cover };
}

// Capa tipográfica para livros sem imagem de capa
export async function typographicCover(title, author) {
  const c = document.createElement("canvas"); c.width = 600; c.height = 900;
  const x = c.getContext("2d");
  const tones = ["#2e3a48", "#583830", "#36483c", "#463e54", "#28282c", "#604e34"];
  x.fillStyle = tones[[...title].reduce((a, ch) => a + ch.charCodeAt(0), 0) % tones.length]; x.fillRect(0, 0, 600, 900);
  x.strokeStyle = "rgba(244,238,226,.25)"; x.strokeRect(24, 24, 552, 852);
  x.fillStyle = "#f4eee2"; x.textAlign = "center";
  const size = title.length < 24 ? 60 : 46;
  x.font = `600 ${size}px ui-serif, "New York", Georgia, serif`;
  const words = title.split(/\s+/), lines = []; let line = "";
  for (const w of words) { const t = (line + " " + w).trim(); if (x.measureText(t).width > 480 && line) { lines.push(line); line = w; } else line = t; }
  if (line) lines.push(line);
  let y = 260; for (const l of lines.slice(0, 5)) { x.fillText(l, 300, y); y += size * 1.18; }
  if (author) { x.font = `italic 30px ui-serif, Georgia, serif`; x.fillStyle = "#dcd4c6"; x.fillText(author, 300, y + 70); }
  return await new Promise((r) => c.toBlob(r, "image/jpeg", 0.88));
}
