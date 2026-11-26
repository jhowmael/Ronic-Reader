"""Núcleo do player: livro em trechos, síntese antecipada com cache, biblioteca e exportação.

Para começar a tocar em poucos segundos, o livro é dividido em *trechos* curtos
(~1 parágrafo, ~45 s de áudio). O player pede o trecho atual e o sintetizador já
vai gerando os próximos em segundo plano. Cada trecho gerado fica em cache no
disco, então voltar, reabrir o livro ou exportar MP3 não gera nada de novo.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .cleaner import _is_heading, clean_pages, looks_like_chapter
from .extractor import count_pages, extract_outline, extract_pages, parse_page_range
from .output import safe_filename
from .splitter import _paragraphs, chunk_text
from .voice_settings import VoiceSettings, resolve_settings

APP_NAME = "Ronic Reader"
SUPPORT_DIR = Path.home() / "Library/Application Support" / APP_NAME
CACHE_DIR = Path.home() / "Library/Caches" / APP_NAME
EXPORT_DIR = Path.home() / "Music" / APP_NAME

SEGMENT_CHARS = 400  # ~25 s de fala: curto para começar a tocar em ~3 s
PREFETCH = 3  # quantos trechos à frente gerar enquanto você ouve


# --------------------------------------------------------------------------- #
# Livro
# --------------------------------------------------------------------------- #


@dataclass
class Segment:
    page: int
    text: str  # parágrafos separados por linha em branco
    cont: bool = False  # True = continua o parágrafo do trecho anterior
    heading: bool = False  # título (capítulo/seção)
    level: int = 0  # 1 = título de capítulo (centralizado), 2 = seção


@dataclass
class Chapter:
    title: str
    segment: int  # índice do primeiro trecho do capítulo


@dataclass
class Book:
    id: str
    name: str
    path: str
    total_pages: int
    segments: list[Segment]
    chapters: list[Chapter]
    aspect: float = 0.707  # largura/altura da página (A4 = 0,707)
    title: str = ""
    author: str = ""
    format: str = "pdf"  # "pdf" ou "epub"

    def chapter_of(self, idx: int) -> int:
        import bisect

        starts = getattr(self, "_starts", None)
        if starts is None:
            starts = self._starts = [c.segment for c in self.chapters]
        return max(0, bisect.bisect_right(starts, idx) - 1)

    def to_json(self) -> dict:
        return {
            "id": self.id, "name": self.name, "total_pages": self.total_pages,
            "aspect": self.aspect, "title": self.title or self.name, "author": self.author, "format": self.format,
            "segments": [asdict(s) for s in self.segments],
            "chapters": [asdict(c) for c in self.chapters],
        }


def file_id(path: Path) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as fh:
        for block in iter(lambda: fh.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()[:16]


def _chapter_starts(pdf: Path, page_numbers: set[int]) -> dict[int, str]:
    """Páginas onde começam capítulos, segundo o sumário (bookmarks) do PDF."""
    outline = extract_outline(pdf)
    if not outline:
        return {}
    levels = sorted({o.level for o in outline})
    level = next((lv for lv in levels
                  if sum(o.level == lv and o.page in page_numbers for o in outline) >= 2), levels[0])
    starts: dict[int, str] = {}
    for o in outline:
        if o.level == level and o.page in page_numbers:
            starts[o.page] = f"{starts[o.page]} / {o.title}" if o.page in starts else (o.title or f"Página {o.page}")
    return starts


def clean_title(raw: str) -> str:
    """Conserta títulos de metadados como "Microsoft Word - CÃ³digo.docx" -> "Código"."""
    text = str(raw or "").strip()
    if any(ch in text for ch in "ÃÂ"):  # UTF-8 lido como PDFDocEncoding/Latin-1
        try:
            from pypdf._codecs import _pdfdoc_encoding

            table = {ch: i for i, ch in enumerate(_pdfdoc_encoding) if ch != "\x00"}
            text = bytes(table.get(ch, ord(ch) if ord(ch) < 256 else 63) for ch in text).decode("utf-8")
        except (ImportError, UnicodeDecodeError, ValueError):
            try:
                text = text.encode("cp1252").decode("utf-8")
            except (UnicodeEncodeError, UnicodeDecodeError):
                pass
    text = re.sub(r"^(Microsoft (Word|PowerPoint)|Word|PowerPoint|Documentos? Google)\s*[-–:]\s*", "", text, flags=re.I)
    text = re.sub(r"\.(docx?|odt|pages|rtf|pptx?|txt|pdf)$", "", text, flags=re.I).strip()
    # títulos genéricos não servem
    if re.fullmatch(r"(untitled|sem t[íi]tulo|documento\d*|document\d*|\W*)", text, flags=re.I):
        return ""
    return text


def _pdf_info(pdf: Path) -> tuple[float, str, str]:
    """Proporção da página e título/autor dos metadados do PDF."""
    from pypdf import PdfReader

    try:
        reader = PdfReader(str(pdf))
        page = reader.pages[0]
        w, h = float(page.mediabox.width), float(page.mediabox.height)
        if (page.get("/Rotate") or 0) % 180:
            w, h = h, w
        meta = reader.metadata or {}
        title = clean_title(meta.get("/Title"))
        author = str(meta.get("/Author") or "").strip()
        aspect = w / h if w > 0 and h > 0 else 0.707
        return min(max(aspect, 0.45), 1.6), title, author
    except Exception:
        return 0.707, "", ""


# "1. Objetivo", "2. Âmbito de Aplicação", "10 Conclusão" (seção de nível 1)
NUMBERED_SECTION_RE = re.compile(r"^(\d{1,2})(\.\d{1,2})*\.?\s+[A-ZÀ-Ý]")
CONNECTOR_END_RE = re.compile(r"\b(DE|DA|DO|DAS|DOS|E|EM|PARA|A|O|AS|OS|COM|NA|NO)$", re.IGNORECASE)
COMPANY_RE = re.compile(r"\b(LTDA|S\.?/?A\.?|EIRELI|ME|INC|LLC)\b\.?", re.IGNORECASE)
LOWER_WORDS = {"de", "da", "do", "das", "dos", "e", "em", "para", "a", "o", "as", "os", "com", "na", "no", "nas", "nos", "por", "à", "ao", "aos"}


def _section_kind(para: str) -> str | None:
    """Tipo de título: 'chap' (Capítulo/Parte), 'num' (seção numerada), 'sub' (subseção 2.1),
    'caps' (linha em maiúsculas) ou None."""
    s = para.strip()
    if len(s) > 90 or "\n" in s or s.endswith((",", ";", ":")):
        return None
    if looks_like_chapter(s):
        return "chap"
    m = NUMBERED_SECTION_RE.match(s)
    if m and len(s.split()) <= 12 and not re.search(r"[.!?]$", s.rstrip('”"')):
        return "sub" if m.group(2) else "num"
    if _is_heading(s):
        return "caps"
    return None


def smart_case(text: str) -> str:
    """'NORMA DE AVALIAÇÃO DE RISCO' -> 'Norma de Avaliação de Risco' (só quando está tudo em maiúsculas)."""
    letters = [c for c in text if c.isalpha()]
    if not letters or any(c.islower() for c in letters):
        return text
    words = text.lower().split()
    return " ".join(w if (i and w in LOWER_WORDS) else w[:1].upper() + w[1:] for i, w in enumerate(words))


def uninformative_name(name: str) -> bool:
    """Nomes de arquivo que não dizem nada: '3855_000_69b1b1f8cbbeb', 'document', 'scan_0001'."""
    n = name.lower()
    words = re.findall(r"[a-zà-ÿ]{3,}", n)
    hexish = re.fullmatch(r"[0-9a-f_\-\s.]+", n) is not None
    return hexish or not words or n in {"document", "documento", "arquivo", "file", "untitled"}


def _title_from_cover(heads: list[tuple[int, str]]) -> str:
    """Junta as linhas em maiúsculas da capa ('NORMA DE AVALIAÇÃO DE' + 'RISCO DE TERCEIROS')."""
    runs: list[str] = []
    for _, text in heads:
        if runs and CONNECTOR_END_RE.search(runs[-1]):
            runs[-1] = f"{runs[-1]} {text}"
        else:
            runs.append(text)
    good = [r for r in runs if not COMPANY_RE.search(r) and len(re.findall(r"[A-Za-zÀ-ÿ]", r)) >= 8]
    return smart_case(max(good, key=len)) if good else ""


def load_book(pdf: Path, pages: str | None = None, extractor: str = "pypdf") -> Book:
    """Extrai, limpa e divide o PDF em trechos curtos, cada um preso à sua página."""
    total = count_pages(pdf)
    raw = extract_pages(pdf, parse_page_range(pages, total), extractor)
    if not any(len(p.text.strip()) >= 20 for p in raw):
        raise ValueError("Este PDF não tem texto selecionável (parece escaneado). "
                         "Faça OCR antes, ex.: ocrmypdf -l por entrada.pdf saida.pdf")
    cleaned = clean_pages(raw)
    chapter_pages = _chapter_starts(pdf, {p.number for p in cleaned})

    segments: list[Segment] = []
    outline_chapters: list[Chapter] = []
    candidates: dict[str, list[Chapter]] = {"chap": [], "num": [], "caps": []}
    cover_heads: list[tuple[int, str]] = []
    buf, buf_page, buf_cont = "", 0, False
    seen_pages: set[int] = set()

    def flush() -> None:
        nonlocal buf
        if buf:
            segments.append(Segment(buf_page, buf, buf_cont))
            buf = ""

    for page, para in _paragraphs(cleaned):
        if buf and page != buf_page:  # um trecho nunca atravessa páginas
            flush()
        if page in chapter_pages and page not in seen_pages:
            flush()
            outline_chapters.append(Chapter(chapter_pages[page], len(segments)))
        seen_pages.add(page)

        kind = _section_kind(para)
        if kind:  # títulos viram um trecho próprio
            flush()
            if kind in candidates:
                candidates[kind].append(Chapter(smart_case(para), len(segments)))
            if kind == "caps" and page == segments_first_page(cleaned):
                cover_heads.append((page, para))
            level = 2 if kind in ("num", "sub") else 1
            segments.append(Segment(page, para, heading=True, level=level))
            continue

        for k, piece in enumerate(chunk_text(para, SEGMENT_CHARS)):
            if buf and len(buf) + len(piece) > SEGMENT_CHARS:
                flush()
            if not buf:
                buf, buf_page, buf_cont = piece, page, k > 0
            else:
                buf = f"{buf} {piece}" if k > 0 else f"{buf}\n\n{piece}"
    flush()

    # Fonte dos capítulos, da mais confiável para a menos: sumário do PDF,
    # "Capítulo/Parte", seções numeradas, linhas em maiúsculas.
    if outline_chapters:
        chapters = outline_chapters
    else:
        chapters = next((candidates[k] for k in ("chap", "num") if len(candidates[k]) >= 2), candidates["caps"])

        def norm(t: str) -> str:
            return re.sub(r"\W+", "", t.lower())

        # Títulos repetidos: o primeiro costuma ser a linha do sumário do próprio
        # documento; o capítulo de verdade é a última ocorrência.
        last = {norm(c.title): k for k, c in enumerate(chapters)}
        chapters = [c for k, c in enumerate(chapters) if last[norm(c.title)] == k]
    if not chapters or chapters[0].segment > 0:
        chapters.insert(0, Chapter("Início", 0))

    aspect, title, author = _pdf_info(pdf)
    if not title and uninformative_name(pdf.stem.split("-", 1)[-1]):
        title = _title_from_cover(cover_heads)
    return Book(file_id(pdf), pdf.stem, str(pdf), total, segments, chapters, aspect, title, author)


ROMAN_OR_NUMBER = re.compile(r"^(?:[IVXLCDM]{1,7}|\d{1,4})\.?$")


def load_epub(path: Path) -> Book:
    """EPUB -> livro em páginas (cada capítulo começa numa página nova), com os capítulos do sumário."""
    from .epub import Block, paginate, read_epub

    eb = read_epub(path)
    for ch in eb.chapters:  # "I" + "Do título." -> "I — Do título"
        merged: list[Block] = []
        skip = False
        for k, b in enumerate(ch.blocks):
            if skip:
                skip = False
                continue
            nxt = ch.blocks[k + 1] if k + 1 < len(ch.blocks) else None
            if b.kind == "h" and ROMAN_OR_NUMBER.match(b.text) and nxt and len(nxt.text) <= 80:
                merged.append(Block("h", f"{b.text} — {nxt.text.rstrip('.')}", b.level or 2))
                skip = True
            else:
                merged.append(b)
        ch.blocks = merged

    segments: list[Segment] = []
    chapters: list[Chapter] = []
    buf, buf_page = "", 0
    current = -1

    def flush() -> None:
        nonlocal buf
        if buf:
            segments.append(Segment(buf_page, buf))
            buf = ""

    last_page = 1
    for page, block, ci in paginate(eb):
        last_page = page
        if ci != current:
            flush()
            chapters.append(Chapter(eb.chapters[ci].title, len(segments)))
            current = ci
        if buf and page != buf_page:
            flush()
        if block.kind == "h":
            flush()
            segments.append(Segment(page, block.text, heading=True, level=1 if block.level <= 2 else 2))
            continue
        for k, piece in enumerate(chunk_text(block.text, SEGMENT_CHARS)):
            if buf and len(buf) + len(piece) > SEGMENT_CHARS:
                flush()
            if not buf:
                buf, buf_page = piece, page
                if k > 0:
                    segments.append(Segment(page, piece, cont=True))
                    buf = ""
                continue
            buf = f"{buf} {piece}" if k > 0 else f"{buf}\n\n{piece}"
    flush()
    if not segments:
        raise ValueError("Não encontrei texto neste EPUB.")
    return Book(file_id(path), path.stem, str(path), last_page, segments, chapters, 0.66,
                eb.title, eb.author, "epub")


def open_book(path: Path) -> Book:
    """PDF ou EPUB."""
    from .epub import is_epub

    return load_epub(path) if is_epub(path) else load_book(path)


def segments_first_page(pages) -> int:
    return next((p.number for p in pages if p.text.strip()), 1)


def _typographic_cover(title: str, author: str, out: Path) -> None:
    """Capa gerada para livros sem imagem de capa: título e autor em tipografia de livro."""
    from PIL import Image, ImageDraw, ImageFont

    w, h = 600, 900
    tones = [(46, 58, 72), (88, 56, 48), (54, 72, 60), (70, 62, 84), (40, 40, 44), (96, 78, 52)]
    bg = tones[sum(map(ord, title)) % len(tones)]
    img = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(img)

    def font(size: int, italic: bool = False):
        for f in ("/System/Library/Fonts/NewYorkItalic.ttf" if italic else "/System/Library/Fonts/NewYork.ttf",
                  "/System/Library/Fonts/Supplemental/Georgia.ttf"):
            try:
                return ImageFont.truetype(f, size)
            except OSError:
                continue
        return ImageFont.load_default(size=size)

    def wrap(text: str, f, width: int) -> list[str]:
        lines, line = [], ""
        for word in text.split():
            test = f"{line} {word}".strip()
            if d.textlength(test, font=f) <= width or not line:
                line = test
            else:
                lines.append(line)
                line = word
        return lines + ([line] if line else [])

    ink = (244, 238, 226)
    tf = font(64 if len(title) < 24 else 50)
    lines = wrap(title, tf, w - 120)[:5]
    y = 250
    for line in lines:
        d.text((w / 2, y), line, font=tf, fill=ink, anchor="mm")
        y += tf.size * 1.18
    d.line([(w / 2 - 50, y + 26), (w / 2 + 50, y + 26)], fill=(*ink, 120), width=2)
    if author:
        d.text((w / 2, y + 80), author, font=font(30, italic=True), fill=(220, 212, 198), anchor="mm")
    d.rectangle([24, 24, w - 24, h - 24], outline=(*ink, 60), width=1)
    img.save(out, "JPEG", quality=88)


def render_cover(pdf: Path, out: Path, width: int = 360) -> Path:
    """Miniatura da 1ª página (capa) para a biblioteca."""
    if out.exists():
        return out
    from .epub import is_epub

    if is_epub(pdf):
        from io import BytesIO

        from PIL import Image

        from .epub import read_epub

        eb = read_epub(pdf)
        out.parent.mkdir(parents=True, exist_ok=True)
        try:
            img = Image.open(BytesIO(eb.cover)).convert("RGB") if eb.cover else None
        except Exception:
            img = None
        if img:
            img.thumbnail((600, 900))
            img.save(out, "JPEG", quality=88)
        else:
            _typographic_cover(eb.title or pdf.stem, eb.author, out)
        return out
    import pypdfium2 as pdfium

    doc = pdfium.PdfDocument(str(pdf))
    try:
        page = doc[0]
        scale = width / page.get_width()
        image = page.render(scale=scale).to_pil()
        out.parent.mkdir(parents=True, exist_ok=True)
        image.convert("RGB").save(out, "JPEG", quality=85)
    finally:
        doc.close()
    return out


# --------------------------------------------------------------------------- #
# Síntese com cache e geração antecipada
# --------------------------------------------------------------------------- #


def settings_key(s: VoiceSettings) -> str:
    return hashlib.sha1(json.dumps(asdict(s), sort_keys=True).encode()).hexdigest()[:10]


HEAD_MIN, HEAD_MAX = 25, 90  # 1ª frase (ou oração, até a vírgula) tocada antes do resto
_SENT_END = re.compile(r"[.!?…][\"'”’»)]*\s+")


class Cancelled(Exception):
    """A voz mudou enquanto o trecho era gerado: o resultado não serve mais."""


def split_head(parts: list[tuple[str | None, str]]) -> tuple[list, list]:
    """Separa a primeira frase (para tocar já) do resto do trecho."""
    if not parts:
        return [], []
    voice, text = parts[0]
    cut = None
    for m in _SENT_END.finditer(text):
        if m.end() >= HEAD_MIN:
            cut = m.end()
            break
    if cut is None or cut > HEAD_MAX:  # frase longa: corta numa vírgula ou espaço
        if len(text) <= HEAD_MAX:
            return [parts[0]], parts[1:]
        window = text[:HEAD_MAX]
        cut = max(window.rfind(", "), window.rfind("; ")) + 1 or window.rfind(" ")
        cut = cut if cut > HEAD_MIN else HEAD_MAX
    head, rest = text[:cut].strip(), text[cut:].strip()
    tail = ([(voice, rest)] if rest else []) + parts[1:]
    return [(voice, head)], tail


class Synthesizer:
    """Gera o áudio dos trechos em segundo plano, guardando cada um em cache no disco.

    - "full": o trecho inteiro (pré-geração dos próximos, exportação).
    - "head"/"tail": primeira frase e resto, numa fila prioritária, para o play
      (e a troca de voz) começar em cerca de 1 segundo.
    """

    def __init__(self) -> None:
        self.settings: VoiceSettings = resolve_settings({}, None)
        self.parts_provider = None  # (book, idx) -> list[(voz, texto)] | None  (vozes por personagem)
        self.variant_provider = None  # (book) -> str: muda a chave do cache quando o elenco muda
        self.generation = 0
        self._engine = None
        self._engine_lock = threading.Lock()
        self._lock = threading.Lock()
        self._futures: dict[str, Future] = {}
        self._pool = self._make_pool()
        self._priority = ThreadPoolExecutor(max_workers=2)
        self._spec: dict[str, Future] = {}  # preparações especulativas, por arquivo de destino
        # pré-geração cede a vez enquanto houver pedido de play (head/tail) em andamento
        self._prio_count = 0
        self._prio_cv = threading.Condition()

    def _make_pool(self) -> ThreadPoolExecutor:
        # Online: alguns em paralelo. Vozes locais dividem a CPU e o mesmo modelo: 1 por vez.
        return ThreadPoolExecutor(max_workers=3 if self.settings.engine == "edge" else 1)

    def set_settings(self, s: VoiceSettings) -> None:
        with self._lock:
            engine_changed = s.engine != self.settings.engine
            self.settings = s
            self.generation += 1  # gerações em andamento com a voz antiga param na próxima frase
            self._engine = None
            old = self._pool
            self._pool = self._make_pool()
            old.shutdown(wait=False, cancel_futures=True)
            for f in self._futures.values():
                f.cancel()
            self._futures.clear()
        if engine_changed:  # mesma família de voz: o modelo já está quente
            self.warm_up()

    def invalidate(self) -> None:
        """O elenco do livro mudou: descarta o que estava na fila."""
        with self._lock:
            self.generation += 1
            for f in self._futures.values():
                f.cancel()
            self._futures.clear()

    def warm_up(self) -> None:
        """Vozes locais: carrega o modelo em segundo plano, para o primeiro play não esperar."""
        if self.settings.engine == "edge":
            return

        def run():
            try:
                engine = self.engine()
                if hasattr(engine, "_speak"):
                    engine._speak("Olá.")
            except Exception as exc:  # aparece de novo, com a mensagem certa, ao tocar
                print("pré-carga da voz falhou:", exc)

        threading.Thread(target=run, daemon=True).start()

    def engine(self):
        with self._engine_lock:
            if self._engine is None:
                from .tts import get_engine

                s = self.settings
                self._engine = get_engine(s.engine, voice=s.voice, rate=s.rate, volume=s.volume,
                                          pitch=s.pitch, expressiveness=s.expressiveness, concurrency=1)
            return self._engine

    # ------------------------------------------------------------------ #
    def parts_for(self, book: Book, idx: int) -> list[tuple[str | None, str]]:
        if self.parts_provider:
            parts = self.parts_provider(book, idx)
            if parts:
                return parts
        return [(None, book.segments[idx].text)]

    def _select(self, book: Book, idx: int, part: str) -> list[tuple[str | None, str]]:
        parts = self.parts_for(book, idx)
        if part == "full":
            return parts
        head, tail = split_head(parts)
        return head if part == "head" else tail

    def path_for(self, book: Book, idx: int, part: str = "full", settings: VoiceSettings | None = None) -> Path:
        settings = settings or self.settings
        ext = ".mp3" if settings.engine == "edge" or _has_lameenc() else ".wav"
        variant = settings_key(settings)
        if self.variant_provider:
            variant += self.variant_provider(book) or ""
        # o texto (e as vozes) entram na chave: nunca toca um áudio que não corresponde
        sel = self._select(book, idx, part)
        key = hashlib.sha1(json.dumps(sel, ensure_ascii=False).encode()).hexdigest()[:10]
        suffix = {"full": "", "head": "-h", "tail": "-t"}[part]
        return CACHE_DIR / book.id / variant / f"{idx:05d}-{key}{suffix}{ext}"

    def _render(self, book: Book, idx: int, part: str, target: Path, gen: int, engine=None) -> Path:
        if target.exists():
            return target
        parts = self._select(book, idx, part)
        if not parts:
            raise Cancelled("trecho vazio")
        target.parent.mkdir(parents=True, exist_ok=True)
        speculative = engine is not None
        priority = part != "full" and not speculative

        def should_stop() -> bool:
            return False if speculative else gen != self.generation

        def wait_turn() -> None:
            if priority:
                return
            with self._prio_cv:
                self._prio_cv.wait_for(lambda: self._prio_count == 0 or should_stop(), timeout=60)

        if priority:
            with self._prio_cv:
                self._prio_count += 1
        try:
            engine = engine or self.engine()
            if hasattr(engine, "synthesize_parts"):
                engine.synthesize_parts(parts, target, should_stop=should_stop, wait_turn=wait_turn)
            else:
                wait_turn()
                engine.synthesize_part([t for _, t in parts], target, label=f"trecho {idx + 1}")
        finally:
            if priority:
                with self._prio_cv:
                    self._prio_count -= 1
                    self._prio_cv.notify_all()
        if should_stop():
            target.unlink(missing_ok=True)
            raise Cancelled("a voz mudou")
        return target

    def _submit(self, pool, book: Book, idx: int, part: str) -> Future:
        target = self.path_for(book, idx, part)
        key = f"{book.id}:{target}"
        f = self._futures.get(key)
        if f is None or f.cancelled() or (f.done() and f.exception() is not None):
            f = pool.submit(self._render, book, idx, part, target, self.generation)
            self._futures[key] = f
        return f

    def speculate(self, book: Book, idx: int, settings: VoiceSettings) -> None:
        """Prepara a 1ª frase do trecho atual numa voz que a pessoa está prestes a escolher
        (mouse sobre a voz no painel). Se ela clicar, a troca toca na hora."""
        if settings_key(settings) == settings_key(self.settings):
            return
        target = self.path_for(book, idx, "head", settings)
        full = self.path_for(book, idx, "full", settings)
        key = str(target)
        with self._lock:
            if target.exists() or full.exists() or key in self._spec:
                return
            if len(self._spec) > 40:  # só as mais recentes importam
                for old in list(self._spec)[:20]:
                    self._spec.pop(old, None)

            def run():
                from .tts import get_engine

                engine = get_engine(settings.engine, voice=settings.voice, rate=settings.rate, volume=settings.volume,
                                    pitch=settings.pitch, expressiveness=settings.expressiveness, concurrency=1)
                return self._render(book, idx, "head", target, self.generation, engine=engine)

            self._spec[key] = self._priority.submit(run)

    def request(self, book: Book, idx: int, part: str = "full") -> Future:
        """Pede o áudio de um trecho e agenda os próximos. Devolve um Future com o caminho."""
        with self._lock:
            if part in ("head", "tail"):
                full = self.path_for(book, idx, "full")
                if part == "head" and full.exists():  # já tem o trecho inteiro: melhor ainda
                    done: Future = Future()
                    done.set_result(full)
                    return done
                spec = self._spec.get(str(self.path_for(book, idx, part)))
                if spec is not None and not spec.cancelled() and not (spec.done() and spec.exception()):
                    for i in range(idx + 1, min(idx + PREFETCH + 1, len(book.segments))):
                        self._submit(self._pool, book, i, "full")
                    return spec  # a preparação feita pelo mouse sobre a voz já está a caminho
                f = self._submit(self._priority, book, idx, part)
                first_next = idx + 1
            else:
                f = self._submit(self._pool, book, idx, "full")
                first_next = idx + 1
            for i in range(first_next, min(idx + PREFETCH + 1, len(book.segments))):
                self._submit(self._pool, book, i, "full")
            return f


def _has_lameenc() -> bool:
    try:
        import lameenc  # noqa: F401

        return True
    except ImportError:
        return False


# --------------------------------------------------------------------------- #
# Biblioteca: livros recentes e posição de leitura
# --------------------------------------------------------------------------- #


class Library:
    def __init__(self) -> None:
        self.file = SUPPORT_DIR / "library.json"
        self.books_dir = SUPPORT_DIR / "books"
        self._lock = threading.Lock()
        try:
            self.data: dict = json.loads(self.file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            self.data = {}

    def _save(self) -> None:
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_suffix(".tmp")
        tmp.write_text(json.dumps(self.data, ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, self.file)

    def store_pdf(self, source: Path, name: str | None = None) -> Path:
        """Guarda uma cópia do PDF na biblioteca (para reabrir pelos recentes)."""
        self.books_dir.mkdir(parents=True, exist_ok=True)
        fid = file_id(source)
        stem = safe_filename(Path(name or source.name).stem, 80)
        from .epub import is_epub

        ext = ".epub" if is_epub(source) else ".pdf"
        dest = self.books_dir / f"{fid}-{stem}{ext}"
        if not dest.exists():
            shutil.copyfile(source, dest)
        return dest

    def touch(self, book: Book) -> dict:
        with self._lock:
            entry = self.data.setdefault(book.id, {"position": 0})
            entry.update(name=book.title or book.name, path=book.path, segments=len(book.segments),
                         total_pages=book.total_pages, format=book.format, opened=time.time())
            self._save()
        (CACHE_DIR / book.id).mkdir(parents=True, exist_ok=True)
        os.utime(CACHE_DIR / book.id)  # marca como usado (limpeza automática do cache)
        return entry

    def set_position(self, book_id: str, position: int, page: int | None = None) -> None:
        with self._lock:
            if book_id in self.data:
                self.data[book_id]["position"] = int(position)
                if page:
                    self.data[book_id]["page"] = int(page)
                self._save()

    # preferências da interface (velocidade, barra lateral...) — fora do navegador,
    # porque a porta do servidor muda a cada execução e o localStorage se perderia
    def prefs(self) -> dict:
        try:
            return json.loads((SUPPORT_DIR / "prefs.json").read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def set_prefs(self, values: dict) -> dict:
        with self._lock:
            prefs = {**self.prefs(), **values}
            SUPPORT_DIR.mkdir(parents=True, exist_ok=True)
            (SUPPORT_DIR / "prefs.json").write_text(json.dumps(prefs, ensure_ascii=False), encoding="utf-8")
            return prefs

    def cover(self, book_id: str) -> Path | None:
        entry = self.data.get(book_id)
        if not entry or not Path(entry.get("path", "")).exists():
            return None
        custom = SUPPORT_DIR / "covers" / f"{book_id}-custom.jpg"
        if entry.get("custom_cover") and custom.exists():
            return custom
        return render_cover(Path(entry["path"]), SUPPORT_DIR / "covers" / f"{book_id}.jpg")

    def rename(self, book_id: str, name: str) -> dict:
        name = " ".join(str(name or "").split())[:120]
        with self._lock:
            entry = self.data.get(book_id)
            if not entry:
                raise ValueError("Livro não encontrado na biblioteca.")
            if name:
                entry["custom_name"] = name
            else:
                entry.pop("custom_name", None)  # nome vazio = volta ao original
            self._save()
            return entry

    def set_cover(self, book_id: str, *, page: int | None = None, image: Path | None = None,
                  data: bytes | None = None, reset: bool = False) -> dict:
        """Capa personalizada: uma página do PDF, uma imagem do disco, ou volta à original."""
        from io import BytesIO

        from PIL import Image, ImageOps

        try:  # fotos do iPhone (HEIC)
            from pillow_heif import register_heif_opener

            register_heif_opener()
        except ImportError:
            pass

        entry = self.data.get(book_id)
        if not entry:
            raise ValueError("Livro não encontrado na biblioteca.")
        out = SUPPORT_DIR / "covers" / f"{book_id}-custom.jpg"
        out.parent.mkdir(parents=True, exist_ok=True)
        if reset:
            out.unlink(missing_ok=True)
        elif page:
            import pypdfium2 as pdfium

            doc = pdfium.PdfDocument(entry["path"])
            try:
                if not 1 <= page <= len(doc):
                    raise ValueError("Página inexistente.")
                pg = doc[page - 1]
                pg.render(scale=600 / pg.get_width()).to_pil().convert("RGB").save(out, "JPEG", quality=88)
            finally:
                doc.close()
        else:
            try:
                img = Image.open(BytesIO(data) if data is not None else image)
                img = ImageOps.exif_transpose(img).convert("RGB")
            except Exception as exc:
                raise ValueError("Não consegui abrir essa imagem. Use JPG, PNG, HEIC ou WebP.") from exc
            img.thumbnail((900, 1300))
            img.save(out, "JPEG", quality=88)
        with self._lock:
            entry["custom_cover"] = not reset
            entry["cover_v"] = int(entry.get("cover_v", 0)) + 1
            self._save()
            return entry

    def remove(self, book_id: str) -> None:
        with self._lock:
            entry = self.data.pop(book_id, None)
            self._save()
        if entry:
            pdf = Path(entry.get("path", ""))
            if pdf.parent == self.books_dir:  # só apaga a cópia interna, nunca o seu arquivo original
                pdf.unlink(missing_ok=True)
            shutil.rmtree(CACHE_DIR / book_id, ignore_errors=True)
            (SUPPORT_DIR / "covers" / f"{book_id}.jpg").unlink(missing_ok=True)

    def recent(self, limit: int = 200) -> list[dict]:
        items = []
        for k, v in self.data.items():
            if Path(v.get("path", "")).exists():
                items.append({"id": k, **v, "name": v.get("custom_name") or v.get("name", "Sem título")})
        return sorted(items, key=lambda x: -x.get("opened", 0))[:limit]


# --------------------------------------------------------------------------- #
# Exportação para MP3 (um arquivo por capítulo)
# --------------------------------------------------------------------------- #


@dataclass
class ExportJob:
    book_id: str
    total: int
    done: int = 0
    status: str = "running"  # running | done | error | cancelled
    message: str = ""
    folder: str = ""
    cancel: threading.Event = field(default_factory=threading.Event)

    def to_json(self) -> dict:
        return {"total": self.total, "done": self.done, "status": self.status,
                "message": self.message, "folder": self.folder}


def export_book(book: Book, synth: Synthesizer, job: ExportJob) -> None:
    """Gera todos os trechos (reaproveitando o cache) e junta por capítulo em ~/Music."""
    try:
        folder = EXPORT_DIR / safe_filename(book.name, 80)
        folder.mkdir(parents=True, exist_ok=True)
        job.folder = str(folder)
        bounds = [c.segment for c in book.chapters] + [len(book.segments)]
        files: list[Path] = []
        for n, chapter in enumerate(book.chapters):
            first, last = bounds[n], bounds[n + 1]
            if first >= last:
                continue
            pieces = []
            for i in range(first, last):
                if job.cancel.is_set():
                    job.status = "cancelled"
                    return
                pieces.append(synth.request(book, i).result())
                job.done += 1
            ext = pieces[0].suffix
            out = folder / f"{n + 1:02d} - {safe_filename(chapter.title)}{ext}"
            if ext == ".wav":
                from .output import merge_audio

                merge_audio(pieces, out)
            else:
                with open(out, "wb") as dst:
                    for p in pieces:
                        dst.write(p.read_bytes())
            files.append(out)
        (folder / f"{safe_filename(book.name)}.m3u").write_text(
            "#EXTM3U\n" + "\n".join(f.name for f in files) + "\n", encoding="utf-8")
        job.status = "done"
    except Exception as exc:  # mostra o erro na interface
        job.status, job.message = "error", str(exc)


def cleanup_cache(max_age_days: int = 30) -> None:
    """Apaga áudios em cache de livros não abertos há muito tempo."""
    if not CACHE_DIR.exists():
        return
    limit = time.time() - max_age_days * 86400
    for d in CACHE_DIR.iterdir():
        try:
            if d.is_dir() and d.stat().st_mtime < limit:
                shutil.rmtree(d, ignore_errors=True)
        except OSError:
            pass

