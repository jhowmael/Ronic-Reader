"""Testes offline (não precisam de internet nem geram áudio)."""

from pathlib import Path

import pytest

from ronic_reader.cleaner import clean_pages, join_pages
from ronic_reader.extractor import Page, extract_outline, extract_pages, parse_page_range
from ronic_reader.output import safe_filename
from ronic_reader.splitter import chunk_text, make_parts
from ronic_reader.voice_settings import resolve_settings


# ------------------------------- páginas ---------------------------------- #
def test_parse_page_range():
    assert parse_page_range(None, 5) == [1, 2, 3, 4, 5]
    assert parse_page_range("2-3", 5) == [2, 3]
    assert parse_page_range("1,4-", 5) == [1, 4, 5]
    assert parse_page_range("3-99", 5) == [3, 4, 5]
    with pytest.raises(ValueError):
        parse_page_range("4-2", 5)


# ------------------------------- limpeza ---------------------------------- #
def _page(n, body):
    return Page(n, f"Meu Livro - Cabeçalho\n{body}\n{n}")


def test_removes_headers_footers_and_joins_lines():
    pages = [
        _page(1, "Esta é uma frase que continua\nna linha seguinte e termina aqui.\n\nNovo parágrafo."),
        _page(2, "Outra página com texto com-\nputador hifenizado."),
        _page(3, "Terceira página."),
    ]
    cleaned = clean_pages(pages)
    text = join_pages(cleaned)
    assert "Cabeçalho" not in text
    assert "continua na linha seguinte" in text
    assert "computador" in text
    assert "Novo parágrafo." in text
    assert not any(line.strip().isdigit() for line in text.splitlines())


def test_sentence_continues_on_next_page():
    pages = [Page(1, "O texto termina sem ponto e"), Page(2, "continua aqui.")]
    assert join_pages(clean_pages(pages)) == "O texto termina sem ponto e continua aqui."


def test_ligatures_and_urls():
    text = join_pages(clean_pages([Page(1, "A ﬁla ﬂui. Veja https://exemplo.com/x agora.")]))
    assert "fila flui" in text and "https" not in text


# ------------------------------- divisão ---------------------------------- #
def test_chunk_text_respects_limit():
    text = "\n\n".join(["Frase curta. " * 40] * 10)
    chunks = chunk_text(text, max_chars=500)
    assert all(len(c) <= 500 for c in chunks)
    assert "".join(chunks).replace(" ", "").replace("\n", "") == text.replace(" ", "").replace("\n", "")


def test_split_by_detected_headings():
    pages = [Page(1, "Capítulo 1\n\nTexto um."), Page(2, "Capítulo 2\n\nTexto dois.")]
    parts, strategy = make_parts(pages, [], "auto")
    assert [p.title for p in parts] == ["Capítulo 1", "Capítulo 2"]
    assert "títulos" in strategy


def test_sample_pdf_end_to_end(tmp_path: Path):
    from make_sample_pdf import build

    pdf = build(tmp_path / "x.pdf")
    raw = extract_pages(pdf, parse_page_range(None, 5))
    parts, strategy = make_parts(clean_pages(raw), extract_outline(pdf), "auto")
    assert "sumário" in strategy
    assert [p.title for p in parts][-1] == "Epílogo"
    full = " ".join(p.text for p in parts)
    assert "Histórias da Serra" not in full  # cabeçalho removido
    assert "manhã seguinte" in full and "estrada de terra" in full  # hifenização desfeita


# ---------------------------- ajustes de voz ------------------------------ #
def test_voice_settings_priority_and_validation():
    s = resolve_settings({"voice": "antonio", "rate": "10"}, "calmo", config={"volume": "+20%"})
    assert s.voice == "pt-BR-AntonioNeural"
    assert s.rate == "+10%"  # CLI vence a predefinição
    assert s.volume == "-5%"  # predefinição vence a config salva
    assert s.pitch == "-4Hz"
    with pytest.raises(ValueError):
        resolve_settings({"rate": "+500%"}, None, config={})
    with pytest.raises(ValueError):
        resolve_settings({"pitch": "grave"}, None, config={})


def test_voice_from_other_engine_falls_back_to_default():
    assert resolve_settings({"engine": "piper", "voice": "francisca"}, None, config={}).voice is None
    assert resolve_settings({"engine": "edge", "voice": "pt_BR-faber-medium"}, None, config={}).voice is None


def test_safe_filename():
    assert safe_filename("Capítulo 3: O Início?") == "Capitulo 3 - O Inicio"
