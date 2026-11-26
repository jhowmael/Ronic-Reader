"""Leitura de EPUB (2 e 3) sem dependências externas.

EPUB é um ZIP com páginas XHTML. A ordem de leitura vem do "spine" do arquivo OPF,
os nomes dos capítulos do sumário (nav.xhtml ou toc.ncx) e a capa do manifesto.
Como EPUB não tem páginas fixas, o texto é dividido em páginas virtuais do tamanho
de uma página de livro, e cada capítulo começa numa página nova.
"""

from __future__ import annotations

import posixpath
import re
import unicodedata
import zipfile
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from xml.etree import ElementTree as ET

PAGE_CHARS = 1500  # ~ uma página de livro de bolso

BLOCK_TAGS = {"p", "div", "li", "blockquote", "pre", "dd", "dt", "td", "figcaption", "section", "article", "aside", "tr"}
HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}
SKIP_TAGS = {"script", "style", "head", "nav", "svg", "math", "rt", "rp"}


@dataclass
class Block:
    kind: str  # "h" (título) ou "p" (parágrafo)
    text: str
    level: int = 0


@dataclass
class EpubChapter:
    title: str
    blocks: list[Block] = field(default_factory=list)


@dataclass
class EpubBook:
    title: str
    author: str
    chapters: list[EpubChapter]
    cover: bytes | None
    language: str = ""


class _TextExtractor(HTMLParser):
    """XHTML -> blocos de texto (títulos e parágrafos), na ordem."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.blocks: list[Block] = []
        self.buf: list[str] = []
        self.skip = 0
        self.heading = 0

    def flush(self) -> None:
        text = " ".join("".join(self.buf).split())
        self.buf = []
        if text:
            self.blocks.append(Block("h" if self.heading else "p", text, self.heading))

    def handle_starttag(self, tag, attrs):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip += 1
        elif tag in HEADING_TAGS:
            self.flush()
            self.heading = int(tag[1])
        elif tag in BLOCK_TAGS:
            self.flush()
        elif tag == "br":
            self.buf.append(" ")
        elif tag == "img":  # imagem com texto alternativo: lê o texto
            alt = dict(attrs).get("alt", "").strip()
            if alt and len(alt) > 3 and not re.search(r"\b(logo|logotipo|ícone|icon|capa|cover)\b", alt, re.I):
                self.buf.append(f" {alt} ")

    def handle_endtag(self, tag):
        tag = tag.lower()
        if tag in SKIP_TAGS:
            self.skip = max(0, self.skip - 1)
        elif tag in HEADING_TAGS:
            self.flush()
            self.heading = 0
        elif tag in BLOCK_TAGS:
            self.flush()

    def handle_data(self, data):
        if not self.skip:
            self.buf.append(data)

    def close(self):
        super().close()
        self.flush()


def _local(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _read_xml(z: zipfile.ZipFile, name: str) -> ET.Element:
    return ET.fromstring(z.read(name))


def _toc_titles(z: zipfile.ZipFile, base: str, manifest: dict, spine_ids: list[str]) -> dict[str, str]:
    """href do capítulo -> título, a partir do nav.xhtml (EPUB 3) ou toc.ncx (EPUB 2)."""
    titles: dict[str, str] = {}
    nav = next((m for m in manifest.values() if "nav" in m["properties"].split()), None)
    try:
        if nav:
            root = _read_xml(z, nav["path"])
            nav_dir = posixpath.dirname(nav["path"])
            for a in root.iter():
                if _local(a.tag) == "a" and a.get("href"):
                    href = posixpath.normpath(posixpath.join(nav_dir, a.get("href").split("#")[0]))
                    text = " ".join("".join(a.itertext()).split())
                    if text and href not in titles:
                        titles[href] = text
        if not titles:
            ncx = next((m for m in manifest.values() if m["media"] == "application/x-dtbncx+xml"), None)
            if ncx:
                root = _read_xml(z, ncx["path"])
                ncx_dir = posixpath.dirname(ncx["path"])
                for point in root.iter():
                    if _local(point.tag) != "navPoint":
                        continue
                    label = next((" ".join("".join(t.itertext()).split()) for t in point.iter() if _local(t.tag) == "text"), "")
                    content = next((c.get("src") for c in point.iter() if _local(c.tag) == "content"), None)
                    if content and label:
                        href = posixpath.normpath(posixpath.join(ncx_dir, content.split("#")[0]))
                        titles.setdefault(href, label)
    except ET.ParseError:
        pass
    return titles


def read_epub(path: Path) -> EpubBook:
    with zipfile.ZipFile(path) as z:
        try:
            container = _read_xml(z, "META-INF/container.xml")
        except KeyError as exc:
            raise ValueError("Este arquivo não parece ser um EPUB válido.") from exc
        opf_path = next(e.get("full-path") for e in container.iter() if _local(e.tag) == "rootfile")
        base = posixpath.dirname(opf_path)
        opf = _read_xml(z, opf_path)

        meta = {"title": "", "creator": "", "language": ""}
        cover_id = None
        manifest: dict[str, dict] = {}
        spine_ids: list[str] = []
        for el in opf.iter():
            tag = _local(el.tag)
            if tag in meta and not meta[tag] and (el.text or "").strip():
                meta[tag] = " ".join(el.text.split())
            elif tag == "meta" and el.get("name") == "cover":
                cover_id = el.get("content")
            elif tag == "item":
                manifest[el.get("id")] = {
                    "path": posixpath.normpath(posixpath.join(base, el.get("href", ""))),
                    "media": el.get("media-type", ""),
                    "properties": el.get("properties", ""),
                }
            elif tag == "itemref" and el.get("linear", "yes") != "no":
                spine_ids.append(el.get("idref"))

        # capa: item marcado como cover-image, ou o <meta name="cover"> apontando para uma imagem
        cover = None
        cover_item = next((m for m in manifest.values() if "cover-image" in m["properties"].split()), None)
        if not cover_item and cover_id in manifest and manifest[cover_id]["media"].startswith("image/"):
            cover_item = manifest[cover_id]
        if cover_item:
            try:
                cover = z.read(cover_item["path"])
            except KeyError:
                cover = None

        toc = _toc_titles(z, base, manifest, spine_ids)
        chapters: list[EpubChapter] = []
        for sid in spine_ids:
            item = manifest.get(sid)
            if not item or "html" not in item["media"]:
                continue
            try:
                raw = z.read(item["path"]).decode("utf-8", errors="replace")
            except KeyError:
                continue
            parser = _TextExtractor()
            parser.feed(raw)
            parser.close()
            blocks = [Block(b.kind, unicodedata.normalize("NFKC", unescape(b.text)), b.level) for b in parser.blocks]
            if not any(len(b.text) > 1 for b in blocks):
                continue
            title = toc.get(item["path"]) or next((b.text for b in blocks if b.kind == "h"), "") or f"Parte {len(chapters) + 1}"
            chapters.append(EpubChapter(title, blocks))

    if not chapters:
        raise ValueError("Não encontrei texto neste EPUB.")
    return EpubBook(meta["title"], meta["creator"], chapters, cover, meta["language"])


def paginate(book: EpubBook, page_chars: int = PAGE_CHARS) -> list[tuple[int, Block, int]]:
    """Distribui os blocos em páginas virtuais: (página, bloco, índice do capítulo)."""
    out: list[tuple[int, Block, int]] = []
    page = 0
    for ci, chapter in enumerate(book.chapters):
        page += 1  # cada capítulo começa numa página nova
        used = 0
        for block in chapter.blocks:
            size = len(block.text) + 60  # 60 ≈ espaço de um parágrafo
            if used and used + size > page_chars and block.kind == "p":
                page += 1
                used = 0
            out.append((page, block, ci))
            used += size
    return out


def is_epub(path: Path) -> bool:
    if path.suffix.lower() == ".epub":
        return True
    try:
        with zipfile.ZipFile(path) as z:
            return z.read("mimetype").strip() == b"application/epub+zip"
    except (zipfile.BadZipFile, KeyError, OSError):
        return False


def clean_title(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()
