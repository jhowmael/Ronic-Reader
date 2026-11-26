"""Limpeza automática do texto extraído do PDF, pensada para leitura em voz alta.

O texto que sai de um PDF vem "quebrado" do jeito que estava diagramado na
página. Para soar natural na voz precisamos:

1. Normalizar caracteres (ligaduras "ﬁ" -> "fi", hífen invisível, espaços estranhos).
2. Remover cabeçalhos/rodapés que se repetem em várias páginas e números de página.
3. Desfazer a hifenização de fim de linha ("compu-\\ntador" -> "computador").
4. Juntar linhas que pertencem ao mesmo parágrafo e preservar quebras reais.
5. Remover ruídos que atrapalham a fala (pontilhados de sumário, URLs longas...).
"""

from __future__ import annotations

import re
import statistics
import unicodedata
from collections import Counter

from .extractor import Page

# --------------------------------------------------------------------------- #
# Expressões regulares usadas na limpeza
# --------------------------------------------------------------------------- #

# Linhas que são apenas número de página: "12", "- 12 -", "Página 12", "12 de 300", "xii"
PAGE_NUMBER_RE = re.compile(
    r"^\s*[-–—]?\s*(p[áa]g(ina)?\.?|page|p\.)?\s*"
    r"(\d{1,4}|[ivxlcdm]{1,7})"
    r"(\s*(de|of|/)\s*\d{1,4})?\s*[-–—]?\s*$",
    re.IGNORECASE,
)
# "Uso interno | Página 4 de 15", "Pág. 4/15": rodapé/cabeçalho com numeração
PAGE_OF_RE = re.compile(r"\bp[áa]g(?:ina|\.)?\s*\d{1,4}\s*(?:de|/|of)\s*\d{1,4}\b", re.IGNORECASE)
# Pontilhado de sumário: "Capítulo 1 .......... 15"
TOC_LEADER_RE = re.compile(r"\s*(\.\s*){4,}\s*\d*\s*$")
URL_RE = re.compile(r"\b(https?://|www\.)\S+", re.IGNORECASE)
MULTISPACE_RE = re.compile(r"[ \t]+")
# Final de frase: ponto, exclamação, interrogação, dois-pontos, reticências,
# opcionalmente seguidos de aspas/parênteses de fechamento.
SENTENCE_END_RE = re.compile(r"[.!?:;…][\"'”’»)\]]*$")
# Títulos típicos de capítulo/seção
HEADING_RE = re.compile(
    r"^(cap[íi]tulo|chapter|parte|part|se[çc][ãa]o|section|pr[óo]logo|ep[íi]logo|"
    r"introdu[çc][ãa]o|conclus[ãa]o|pref[áa]cio|ap[êe]ndice)\b",
    re.IGNORECASE,
)

# Quantas linhas do topo/base de cada página são candidatas a cabeçalho/rodapé
# (cabeçalhos corporativos costumam ter avisos de várias linhas)
EDGE_LINES = 6


def _normalize_chars(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)  # desfaz ligaduras ﬁ, ﬂ, etc.
    text = text.replace("­", "")  # hífen "suave" (invisível)
    text = text.replace(" ", " ").replace(" ", " ").replace("​", "")
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n")
    # remove caracteres de controle (exceto quebra de linha e tab)
    return "".join(ch for ch in text if ch in "\n\t" or unicodedata.category(ch)[0] != "C")


def _line_key(line: str) -> str:
    """Chave para comparar cabeçalhos/rodapés entre páginas (ignora números)."""
    return re.sub(r"\d+", "#", MULTISPACE_RE.sub(" ", line.strip().lower()))


def _find_repeated_edges(pages_lines: list[list[str]]) -> set[str]:
    """Descobre linhas que se repetem no topo/base de muitas páginas (cabeçalhos/rodapés)."""
    if len(pages_lines) < 3:
        return set()

    counter: Counter[str] = Counter()
    for lines in pages_lines:
        non_empty = [l for l in lines if l.strip()]
        edges = non_empty[:EDGE_LINES] + non_empty[-EDGE_LINES:]
        counter.update({_line_key(l) for l in edges})  # set: conta 1x por página

    threshold = max(3, int(len(pages_lines) * 0.4))
    return {key for key, n in counter.items() if n >= threshold and key.strip("# ")}


def _strip_edges(lines: list[str], repeated: set[str]) -> list[str]:
    """Remove cabeçalhos/rodapés repetidos e números de página do topo e da base."""

    def is_noise(line: str) -> bool:
        return _line_key(line) in repeated or bool(PAGE_NUMBER_RE.match(line))

    # remove as linhas repetidas que estiverem na faixa do topo e da base,
    # mesmo que não sejam as primeiras (ex.: aviso de 3 linhas + "Página 4 de 15")
    idx = [i for i, l in enumerate(lines) if l.strip()]
    edge = set(idx[:EDGE_LINES] + idx[-EDGE_LINES:])
    lines = [l for i, l in enumerate(lines) if not (i in edge and is_noise(l))]
    # "página X de Y" curto em qualquer lugar é sempre numeração, nunca texto
    return [l for l in lines if not (PAGE_OF_RE.search(l) and len(l.strip()) <= 80)]


def looks_like_chapter(para: str) -> bool:
    """Parágrafo que abre um capítulo: "Capítulo 3", "PARTE II", "Introdução"...

    Exige letra maiúscula no início, para não confundir frases como
    "seção 13 deste Código." com títulos.
    """
    s = para.strip()
    return (
        bool(HEADING_RE.match(s)) and len(s) <= 80 and s[:1].isupper()
        and len(s.split()) <= 12 and not s.endswith((",", ";"))
    )


def _is_heading(line: str) -> bool:
    s = line.strip()
    if not s or len(s) > 80:
        return False
    if looks_like_chapter(s):
        return True
    letters = [c for c in s if c.isalpha()]
    # Linha curta toda em MAIÚSCULAS e sem pontuação final costuma ser título
    return len(letters) >= 4 and all(c.isupper() for c in letters) and not SENTENCE_END_RE.search(s)


def _join_lines(lines: list[str], typical_len: float) -> str:
    """Reconstrói parágrafos a partir das linhas "diagramadas" de uma página."""
    paragraphs: list[str] = []
    current = ""
    prev_raw_len = 0

    for raw in lines:
        line = MULTISPACE_RE.sub(" ", raw).strip()
        line = TOC_LEADER_RE.sub("", line)

        if not line:  # linha em branco = fim de parágrafo
            if current:
                paragraphs.append(current)
                current = ""
            continue

        if _is_heading(line):  # títulos viram parágrafos próprios
            if current:
                paragraphs.append(current)
            paragraphs.append(line)
            current = ""
            prev_raw_len = 0
            continue

        if not current:
            current = line
        elif re.search(r"\w-$", current) and line[:1].islower():
            # hifenização de fim de linha: "compu-" + "tador"
            current = current[:-1] + line
        elif SENTENCE_END_RE.search(current) and prev_raw_len < typical_len * 0.8:
            # linha anterior terminou frase E era curta -> parágrafo acabou
            paragraphs.append(current)
            current = line
        else:
            current = f"{current} {line}"
        prev_raw_len = len(line)

    if current:
        paragraphs.append(current)
    return "\n\n".join(paragraphs)


def _typical_line_length(pages_lines: list[list[str]]) -> float:
    lengths = [len(l.strip()) for lines in pages_lines for l in lines if len(l.strip()) > 15]
    if not lengths:
        return 60.0
    # percentil ~75: o comprimento de uma linha "cheia" de texto corrido
    return float(statistics.quantiles(lengths, n=4)[-1]) if len(lengths) >= 4 else float(max(lengths))


def _speech_polish(text: str, keep_urls: bool) -> str:
    """Pequenos ajustes para a fala soar melhor."""
    if not keep_urls:
        text = URL_RE.sub("", text)
    text = re.sub(r"^[•·▪●◦■□➢►\-–]\s*", "", text, flags=re.MULTILINE)  # marcadores de lista
    text = re.sub(r"\s+([,.;:!?])", r"\1", text)  # espaço antes de pontuação
    text = re.sub(r"\[\d+(,\s*\d+)*\]", "", text)  # referências tipo [12] ou [3, 4]
    text = MULTISPACE_RE.sub(" ", text)
    return "\n\n".join(p.strip() for p in text.split("\n\n") if p.strip())


def clean_pages(pages: list[Page], *, keep_urls: bool = False) -> list[Page]:
    """Limpa cada página e devolve novas Page com o texto pronto para leitura.

    O texto de cada página fica com parágrafos separados por linha em branco.
    """
    pages_lines = [_normalize_chars(p.text).split("\n") for p in pages]
    repeated = _find_repeated_edges(pages_lines)
    pages_lines = [_strip_edges(lines, repeated) for lines in pages_lines]
    typical = _typical_line_length(pages_lines)

    return [
        Page(p.number, _speech_polish(_join_lines(lines, typical), keep_urls))
        for p, lines in zip(pages, pages_lines)
    ]


def join_pages(pages: list[Page]) -> str:
    """Junta páginas limpas, emendando frases que continuam na página seguinte."""
    out = ""
    for page in pages:
        text = page.text.strip()
        if not text:
            continue
        if not out:
            out = text
        elif re.search(r"\w-$", out) and text[:1].islower():
            out = out[:-1] + text  # palavra hifenizada entre páginas
        elif not SENTENCE_END_RE.search(out) and text[:1].islower():
            out = f"{out} {text}"  # frase continua na próxima página
        else:
            out = f"{out}\n\n{text}"
    return out
