"""Extração local de texto e sumário (bookmarks) do PDF.

Nada aqui acessa a internet: tudo roda com pypdf (padrão, rápido) ou
pdfplumber (mais lento, às vezes melhor em PDFs com layout complicado).
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass
class Page:
    number: int  # número da página no PDF, começando em 1
    text: str


@dataclass
class OutlineItem:
    title: str
    page: int  # página (1-based) onde o capítulo começa
    level: int  # 0 = nível mais alto do sumário


def parse_page_range(spec: str | None, total: int) -> list[int]:
    """Converte "5-20", "1,3,10-12" ou "30-" em uma lista ordenada de páginas.

    Páginas são 1-based e limitadas ao total do documento.
    """
    if not spec:
        return list(range(1, total + 1))

    pages: set[int] = set()
    for part in spec.replace(" ", "").split(","):
        if not part:
            continue
        if "-" in part:
            start_s, end_s = part.split("-", 1)
            start = int(start_s) if start_s else 1
            end = int(end_s) if end_s else total
        else:
            start = end = int(part)
        if start < 1 or end < start:
            raise ValueError(f"Intervalo de páginas inválido: {part!r}")
        pages.update(range(start, min(end, total) + 1))

    if not pages:
        raise ValueError(f"Nenhuma página válida em {spec!r} (o PDF tem {total} páginas)")
    return sorted(pages)


def count_pages(pdf_path: Path) -> int:
    from pypdf import PdfReader

    return len(PdfReader(str(pdf_path)).pages)


def extract_pages(pdf_path: Path, pages: list[int], engine: str = "pypdf") -> list[Page]:
    """Extrai o texto bruto das páginas pedidas."""
    if engine == "pdfplumber":
        import pdfplumber

        with pdfplumber.open(str(pdf_path)) as pdf:
            return [
                Page(n, pdf.pages[n - 1].extract_text() or "")
                for n in pages
            ]

    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    if reader.is_encrypted:
        # Muitos PDFs "protegidos" usam senha vazia apenas para restringir edição.
        reader.decrypt("")
    return [Page(n, reader.pages[n - 1].extract_text() or "") for n in pages]


def extract_outline(pdf_path: Path) -> list[OutlineItem]:
    """Lê o sumário (bookmarks) do PDF, se existir. Usado para dividir por capítulos."""
    from pypdf import PdfReader

    reader = PdfReader(str(pdf_path))
    items: list[OutlineItem] = []

    def walk(nodes, level: int) -> None:
        for node in nodes:
            if isinstance(node, list):  # lista aninhada = filhos do item anterior
                walk(node, level + 1)
                continue
            try:
                page_idx = reader.get_destination_page_number(node)
            except Exception:
                continue
            if page_idx is None or page_idx < 0:
                continue
            title = (getattr(node, "title", None) or "").strip()
            items.append(OutlineItem(title=title, page=page_idx + 1, level=level))

    try:
        walk(reader.outline, 0)
    except Exception:
        return []
    return items
