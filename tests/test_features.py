"""Testes das funções novas: EPUB, personagens, início rápido e catálogo de vozes."""

import zipfile
from pathlib import Path

from ronic_reader import voices
from ronic_reader.player import split_head
from ronic_reader.voice_settings import engine_of_voice


# ------------------------------------------------------------------ EPUB
def _make_epub(path: Path) -> Path:
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml", """<?xml version="1.0"?><container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
<rootfiles><rootfile full-path="OPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles></container>""")
        z.writestr("OPS/content.opf", """<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">
<metadata xmlns:dc="http://purl.org/dc/elements/1.1/"><dc:title>Livro Teste</dc:title><dc:creator>Autora</dc:creator></metadata>
<manifest><item id="nav" href="nav.xhtml" media-type="application/xhtml+xml" properties="nav"/>
<item id="c1" href="c1.xhtml" media-type="application/xhtml+xml"/><item id="c2" href="c2.xhtml" media-type="application/xhtml+xml"/></manifest>
<spine><itemref idref="c1"/><itemref idref="c2"/></spine></package>""")
        z.writestr("OPS/nav.xhtml", """<html xmlns="http://www.w3.org/1999/xhtml"><body><nav><ol>
<li><a href="c1.xhtml">A chegada</a></li><li><a href="c2.xhtml">O segredo</a></li></ol></nav></body></html>""")
        z.writestr("OPS/c1.xhtml", """<html><body><h2>I</h2><p>A chegada.</p><p>Era uma manhã fria.</p>
<p>— Quem está aí? perguntou Marina.</p><p>— Sou eu, respondeu o avô.</p></body></html>""")
        z.writestr("OPS/c2.xhtml", "<html><body><h2>O segredo</h2><p>Na segunda noite, um barulho.</p></body></html>")
    return path


def test_epub_reads_chapters_and_pages(tmp_path):
    from ronic_reader.epub import is_epub, read_epub
    from ronic_reader.player import open_book

    epub = _make_epub(tmp_path / "livro.epub")
    assert is_epub(epub)
    eb = read_epub(epub)
    assert (eb.title, eb.author) == ("Livro Teste", "Autora")
    assert [c.title for c in eb.chapters] == ["A chegada", "O segredo"]
    book = open_book(epub)
    assert book.format == "epub" and book.title == "Livro Teste"
    assert book.segments[0].heading and book.segments[0].text == "I — A chegada"  # "I" + título juntos
    assert book.segments[book.chapters[1].segment].page > 1  # capítulo novo, página nova


# ---------------------------------------------------------- início rápido
def test_split_head_short_first_clause():
    head, tail = split_head([(None, "Era uma manhã fria quando Marina desceu do ônibus. O vento soprava.")])
    assert head[0][1] == "Era uma manhã fria quando Marina desceu do ônibus."
    assert tail[0][1] == "O vento soprava."
    long = "Palavra " * 40
    head, tail = split_head([(None, long)])
    assert len(head[0][1]) <= 90 and tail


# ------------------------------------------------------------ catálogo
def test_catalog_engines_and_genders():
    for v in voices.catalog():
        assert engine_of_voice(v["id"]) == v["engine"], v["id"]
        assert v["gender"] in ("F", "M")
    assert len([v for v in voices.catalog() if v["engine"] == "kokoro"]) == 11
    assert all(v["region"] for v in voices.catalog())
    assert voices.find("pt-BR-ThalitaMultilingualNeural")


# ------------------------------------------------- narração por personagem
def test_narrator_gender_detection():
    from ronic_reader.narration import analyze, narrator_voices, voice_for
    from ronic_reader.player import Book, Chapter, Segment

    segs = [Segment(1, "Eu estava cansada naquela noite e eu mesma abri a janela do meu quarto para ver a minha rua.")] * 6
    book = Book("t", "t", "t", 1, segs, [Chapter("Início", 0)])
    a = analyze(book)
    assert a["book"] == {"person": 1, "gender": "F"}
    data = {"enabled": True, "voices": {}, "gender": "auto", "analysis": a}
    main = "pt-BR-AntonioNeural"
    v = voice_for(data, book, 0, "edge", main)
    assert voices.gender_of(v) == "F"  # narradora com voz feminina
    data["enabled"] = False
    assert voice_for(data, book, 0, "edge", main) is None
    assert narrator_voices(data, "edge", main)["M"] == main
