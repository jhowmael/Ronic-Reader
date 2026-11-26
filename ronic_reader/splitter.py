"""Divisão do texto em partes (arquivos de áudio) e em blocos (requisições de TTS).

- *Parte*  = um arquivo de áudio final (ex.: um capítulo).
- *Bloco*  = pedaço pequeno de texto enviado de cada vez ao motor de voz.
  Blocos pequenos deixam a síntese mais robusta (se um falhar, só ele é refeito)
  e permitem processar vários em paralelo.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from .cleaner import SENTENCE_END_RE, join_pages, looks_like_chapter
from .extractor import OutlineItem, Page

# Em média uma voz neural lê ~900 caracteres por minuto em português.
CHARS_PER_MINUTE = 900


@dataclass
class Part:
    title: str
    text: str
    first_page: int
    last_page: int

    @property
    def minutes(self) -> float:
        return len(self.text) / CHARS_PER_MINUTE


# --------------------------------------------------------------------------- #
# Estratégias de divisão em partes
# --------------------------------------------------------------------------- #


def split_by_outline(pages: list[Page], outline: list[OutlineItem], level: int | None = None) -> list[Part]:
    """Usa o sumário (bookmarks) do PDF: cada item vira uma parte."""
    if not pages or not outline:
        return []
    page_numbers = {p.number for p in pages}
    if level is None:
        # nível mais alto que tenha pelo menos 2 capítulos dentro do intervalo escolhido
        levels = sorted({o.level for o in outline})
        level = next(
            (lv for lv in levels if sum(o.level == lv and o.page in page_numbers for o in outline) >= 2),
            levels[0],
        )

    # Capítulos dentro do intervalo; se vários começam na mesma página, junta títulos
    starts: dict[int, list[str]] = {}
    for item in outline:
        if item.level == level and item.page in page_numbers:
            starts.setdefault(item.page, []).append(item.title or f"Página {item.page}")
    if not starts:
        return []

    boundaries = sorted(starts)
    parts: list[Part] = []
    first = pages[0].number
    if boundaries[0] > first:  # páginas antes do primeiro capítulo
        boundaries.insert(0, first)
        starts[first] = ["Início"]

    for i, start in enumerate(boundaries):
        end = boundaries[i + 1] - 1 if i + 1 < len(boundaries) else pages[-1].number
        chunk = [p for p in pages if start <= p.number <= end]
        text = join_pages(chunk)
        if text.strip():
            parts.append(Part(" / ".join(starts[start]), text, chunk[0].number, chunk[-1].number))
    return parts


def _paragraphs(pages: list[Page]) -> list[tuple[int, str]]:
    """Lista (página, parágrafo), emendando frases que continuam na página seguinte."""
    out: list[tuple[int, str]] = []
    for page in pages:
        for i, para in enumerate(p for p in page.text.split("\n\n") if p.strip()):
            if i == 0 and out:
                prev_page, prev = out[-1]
                if re.search(r"\w-$", prev) and para[:1].islower():
                    out[-1] = (prev_page, prev[:-1] + para)
                    continue
                if not SENTENCE_END_RE.search(prev) and para[:1].islower():
                    out[-1] = (prev_page, f"{prev} {para}")
                    continue
            out.append((page.number, para))
    return out


def split_by_headings(pages: list[Page]) -> list[Part]:
    """Procura títulos como "Capítulo 3", "PARTE II", "Introdução" no começo dos parágrafos."""
    parts: list[Part] = []
    title, buf, first_page, last_page = "Início", [], pages[0].number, pages[0].number

    for page_no, para in _paragraphs(pages):
        is_title = looks_like_chapter(para)
        if is_title and buf:
            parts.append(Part(title, "\n\n".join(buf), first_page, last_page))
            buf, first_page = [], page_no
        if is_title:
            title = para
        buf.append(para)
        last_page = page_no

    if buf:
        parts.append(Part(title, "\n\n".join(buf), first_page, last_page))
    return parts if len(parts) >= 2 else []


def split_by_pages(pages: list[Page], per_part: int) -> list[Part]:
    parts = []
    for i in range(0, len(pages), per_part):
        chunk = pages[i : i + per_part]
        text = join_pages(chunk)
        if text.strip():
            a, b = chunk[0].number, chunk[-1].number
            parts.append(Part(f"Páginas {a}-{b}" if a != b else f"Página {a}", text, a, b))
    return parts


def split_by_size(pages: list[Page], max_chars: int) -> list[Part]:
    """Partes de tamanho aproximado (em caracteres), sempre cortando em fim de parágrafo."""
    parts: list[Part] = []
    buf: list[str] = []
    size, first, last = 0, pages[0].number, pages[0].number

    for page_no, para in _paragraphs(pages):
        if buf and size + len(para) > max_chars:
            parts.append(Part(f"Parte {len(parts) + 1}", "\n\n".join(buf), first, last))
            buf, size, first = [], 0, page_no
        buf.append(para)
        size += len(para) + 2
        last = page_no
    if buf:
        parts.append(Part(f"Parte {len(parts) + 1}", "\n\n".join(buf), first, last))
    return parts


def make_parts(
    pages: list[Page],
    outline: list[OutlineItem],
    mode: str = "auto",
    *,
    pages_per_part: int = 10,
    max_chars: int = 15 * CHARS_PER_MINUTE,
    outline_level: int | None = None,
) -> tuple[list[Part], str]:
    """Divide o documento e informa qual estratégia foi usada de fato."""
    pages = [p for p in pages if p.text.strip()]
    if not pages:
        return [], mode

    if mode == "none":
        p = pages
        return [Part("Completo", join_pages(p), p[0].number, p[-1].number)], "none"
    if mode == "pages":
        return split_by_pages(pages, pages_per_part), "pages"
    if mode == "size":
        return split_by_size(pages, max_chars), "size"

    if mode in ("auto", "chapters"):
        parts = split_by_outline(pages, outline, outline_level)
        if parts:
            return parts, "chapters (sumário do PDF)"
        parts = split_by_headings(pages)
        if parts:
            return parts, "chapters (títulos detectados)"
        if mode == "chapters":
            print("! Nenhum capítulo encontrado; dividindo por tamanho.")
        return split_by_size(pages, max_chars), "size"

    raise ValueError(f"Modo de divisão desconhecido: {mode}")


# --------------------------------------------------------------------------- #
# Blocos para o motor de TTS
# --------------------------------------------------------------------------- #

SENTENCE_SPLIT_RE = re.compile(r"(?<=[.!?…])[\"'”’»)]*\s+")


def split_sentences(text: str) -> list[str]:
    return [s.strip() for s in SENTENCE_SPLIT_RE.split(text) if s.strip()]


def chunk_text(text: str, max_chars: int = 3000) -> list[str]:
    """Agrupa parágrafos em blocos de até `max_chars`, sem cortar frases no meio."""
    chunks: list[str] = []
    buf = ""

    def push(piece: str, sep: str) -> None:
        nonlocal buf
        if buf and len(buf) + len(sep) + len(piece) > max_chars:
            chunks.append(buf)
            buf = piece
        else:
            buf = f"{buf}{sep}{piece}" if buf else piece

    for para in text.split("\n\n"):
        para = para.strip()
        if not para:
            continue
        if len(para) <= max_chars:
            push(para, "\n\n")
            continue
        # parágrafo gigante: quebra por frases (e, em último caso, por palavras)
        for sentence in split_sentences(para):
            while len(sentence) > max_chars:
                cut = sentence.rfind(" ", 0, max_chars)
                cut = cut if cut > 0 else max_chars
                push(sentence[:cut], " ")
                sentence = sentence[cut:].strip()
            push(sentence, " ")
    if buf:
        chunks.append(buf)
    return chunks
