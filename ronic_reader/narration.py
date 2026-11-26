"""Narração por personagem: o livro é lido com voz de narrador ou de narradora,
conforme quem narra cada trecho.

Só regras de português, sem IA (instantâneo e leve):
- 1ª pessoa: muitos "eu/me/meu/minha" na narração;
- gênero de quem narra pela concordância: "eu estava cansada", "eu mesma",
  "obrigado", "sozinho";
- capítulo a capítulo, para livros com mais de um narrador.

As escolhas (ligado/desligado, vozes, gênero forçado) ficam salvas por livro.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from pathlib import Path

from . import voices as catalog

FIRST_PERSON = re.compile(r"\b(?:eu|me|mim|meu|minha|meus|minhas|comigo)\b", re.I)
NARRATOR_ADJ = re.compile(
    r"\beu\s+(?:estava|estou|era|sou|fui|fiquei|ficara|ficava|andava|vivia|me\s+sentia|me\s+senti|"
    r"me\s+achava|me\s+achei|parecia|continuava|permaneci|seria|ficaria|estaria)\s+"
    r"(?:muito\s+|tão\s+|um\s+pouco\s+|meio\s+)?(?P<adj>[a-zà-ÿ]{4,}?)(?P<g>[oa]s?)\b", re.I)
FIXED_F = re.compile(r"\b(?:eu mesma|obrigada|sozinha|eu própria|eu propria)\b", re.I)
FIXED_M = re.compile(r"\b(?:eu mesmo|obrigado|sozinho|eu próprio|eu proprio)\b", re.I)
DIALOGUE = re.compile(r"^\s*[—–]")  # falas não contam: o "eu" ali é de quem fala


def _votes(text: str) -> dict:
    f = len(FIXED_F.findall(text)) + sum(1 for m in NARRATOR_ADJ.finditer(text) if m.group("g").startswith("a"))
    m = len(FIXED_M.findall(text)) + sum(1 for m in NARRATOR_ADJ.finditer(text) if m.group("g").startswith("o"))
    return {"F": f, "M": m, "fp": len(FIRST_PERSON.findall(text)), "w": len(text.split())}


def analyze(book) -> dict:
    """Narrador do livro e de cada capítulo (só a narração, sem as falas)."""
    total = {"F": 0, "M": 0, "fp": 0, "w": 0}
    chapters: dict[int, dict] = {}
    for idx, seg in enumerate(book.segments):
        if seg.heading:
            continue
        narration = "\n".join(p for p in seg.text.split("\n\n") if not DIALOGUE.match(p))
        v = _votes(narration)
        ch = chapters.setdefault(book.chapter_of(idx), {"F": 0, "M": 0, "fp": 0, "w": 0})
        for k in v:
            ch[k] += v[k]
            total[k] += v[k]

    def verdict(v: dict) -> dict:
        first = v["w"] > 0 and v["fp"] / v["w"] > 0.025
        g = "F" if v["F"] > v["M"] else "M" if v["M"] > v["F"] else "?"
        return {"person": 1 if first else 3, "gender": g if first else "?"}

    book_v = verdict(total)
    other = {}
    for ch, v in chapters.items():
        cv = verdict(v)
        # só muda quando a evidência no capítulo é clara
        if v["w"] > 150 and cv["person"] == 1 and abs(v["F"] - v["M"]) >= 2 and cv["gender"] != book_v["gender"]:
            other[ch] = cv["gender"]
    return {"book": book_v, "chapters": other}


class NarrationStore:
    DEFAULT = {"enabled": False, "voices": {}, "gender": "auto"}

    def __init__(self, folder: Path) -> None:
        self.folder = folder
        self._lock = threading.Lock()
        self._cache: dict[str, dict] = {}

    def _path(self, book_id: str) -> Path:
        return self.folder / f"{book_id}.json"

    def load(self, book) -> dict:
        with self._lock:
            if book.id not in self._cache:
                try:
                    data = json.loads(self._path(book.id).read_text(encoding="utf-8"))
                except (OSError, ValueError):
                    data = {}
                for k, v in self.DEFAULT.items():
                    data.setdefault(k, v if not isinstance(v, dict) else dict(v))
                self._cache[book.id] = data
            data = self._cache[book.id]
        if "analysis" not in data:  # análise rápida (regras), feita uma vez por livro
            data["analysis"] = analyze(book)
            self.save(book.id)
        return data

    def save(self, book_id: str) -> None:
        with self._lock:
            data = self._cache.get(book_id)
            if data is None:
                return
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self._path(book_id).with_suffix(".tmp")
            tmp.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            tmp.replace(self._path(book_id))

    def update(self, book, values: dict, engine: str) -> dict:
        data = self.load(book)
        if "enabled" in values:
            data["enabled"] = bool(values["enabled"])
        if values.get("gender") in ("auto", "F", "M"):
            data["gender"] = values["gender"]
        for g in ("F", "M"):
            v = (values.get("voices") or {}).get(g)
            if v:
                data["voices"][f"{engine}:{g}"] = v
        self.save(book.id)
        return data


def narrator_voices(data: dict, engine: str, main_voice: str) -> dict:
    """Voz de narrador (M) e de narradora (F) para o motor atual."""
    out = {}
    main_g = catalog.gender_of(main_voice)
    for g in ("F", "M"):
        chosen = data["voices"].get(f"{engine}:{g}")
        if chosen and (catalog.find(chosen) or {}).get("engine") == engine:
            out[g] = chosen
        elif main_g == g:
            out[g] = main_voice
        else:
            out[g] = next(iter(catalog.pool(engine, g)), main_voice)
    return out


def voice_for(data: dict, book, idx: int, engine: str, main_voice: str) -> str | None:
    """Voz do trecho, ou None para a voz principal."""
    if not data.get("enabled"):
        return None
    a = data["analysis"]
    g = data.get("gender", "auto")
    if g == "auto":
        g = a["chapters"].get(str(book.chapter_of(idx)), a["chapters"].get(book.chapter_of(idx), a["book"]["gender"]))
    if g not in ("F", "M"):
        return None
    v = narrator_voices(data, engine, main_voice)[g]
    return None if v == main_voice else v


def variant(data: dict, engine: str, main_voice: str) -> str:
    if not data.get("enabled"):
        return ""
    blob = json.dumps([data.get("gender"), data["analysis"], narrator_voices(data, engine, main_voice)], sort_keys=True)
    return "-n" + hashlib.sha1(blob.encode()).hexdigest()[:8]
