"""Narração por contexto: descobre quantos narradores o livro tem e lê cada trecho
com a voz do narrador daquele capítulo.

Só regras (instantâneo, sem IA):
1. Capítulos de ponto de vista: títulos com nome de personagem que se repetem
   ("3 — Briana", "Jacob") viram narradores com esse nome.
2. Senão, narração em 1ª pessoa com gênero pela concordância ("eu estava cansada",
   "obrigado"), capítulo a capítulo: Narrador e/ou Narradora.
3. Senão (3ª pessoa), um narrador só.
"""

from __future__ import annotations

import hashlib
import json
import re
import threading
from collections import Counter
from pathlib import Path

from . import voices as catalog

FIRST_PERSON = re.compile(r"\b(?:eu|me|mim|meu|minha|meus|minhas|comigo)\b", re.I)
NARRATOR_ADJ = re.compile(
    r"\beu\s+(?:estava|estou|era|sou|fui|fiquei|ficara|ficava|andava|vivia|me\s+sentia|me\s+senti|"
    r"me\s+achava|me\s+achei|parecia|continuava|permaneci|seria|ficaria|estaria)\s+"
    r"(?:muito\s+|tão\s+|um\s+pouco\s+|meio\s+)?(?P<adj>[a-zà-ÿ]{4,}?)(?P<g>[oa]s?)\b", re.I)
FIXED_F = re.compile(r"\b(?:eu mesma|obrigada|sozinha|eu própria)\b", re.I)
FIXED_M = re.compile(r"\b(?:eu mesmo|obrigado|sozinho|eu próprio)\b", re.I)
DIALOGUE = re.compile(r"^\s*[—–]")
TITLE_PREFIX = re.compile(r"^\s*(?:cap[íi]tulo|parte|chapter)?\s*(?:\d+|[IVXLCDM]+)?\s*[-–—:.·|]*\s*", re.I)
PERSON_NAME = re.compile(r"^[A-ZÀ-Ý][a-zà-ÿ]+(?:\s+[A-ZÀ-Ý][a-zà-ÿ]+)?$")
MALE_A = {"luca", "joshua", "elias", "jonas", "nicolas", "lucas", "thomas", "tomas", "andreas", "mattias"}
FEMALE_O = {"rocio", "consuelo", "socorro", "amparo"}


def _votes(text: str) -> Counter:
    v = Counter(F=len(FIXED_F.findall(text)), M=len(FIXED_M.findall(text)),
                fp=len(FIRST_PERSON.findall(text)), w=len(text.split()))
    for m in NARRATOR_ADJ.finditer(text):
        v["F" if m.group("g").startswith("a") else "M"] += 1
    return v


def _gender(v: Counter, name: str = "") -> str:
    if v["F"] != v["M"]:
        return "F" if v["F"] > v["M"] else "M"
    n = name.lower().split()[0] if name else ""
    if n:
        if n in MALE_A or n.endswith(("o", "os", "r", "l", "z", "el")) and n not in FEMALE_O:
            return "M"
        if n.endswith(("a", "e", "y")) or n in FEMALE_O:
            return "F"
    return "?"


def analyze(book) -> dict:
    """{"narrators": [{id, name, gender, chapters}], "by_chapter": {cap: id}}"""
    per: dict[int, Counter] = {}
    for idx, seg in enumerate(book.segments):
        if seg.heading:
            continue
        narration = "\n".join(p for p in seg.text.split("\n\n") if not DIALOGUE.match(p))
        per.setdefault(book.chapter_of(idx), Counter()).update(_votes(narration))

    # 1) capítulos de ponto de vista: nome de personagem repetido no título
    names = {}
    for k, ch in enumerate(book.chapters):
        rest = TITLE_PREFIX.sub("", ch.title or "").strip()
        if PERSON_NAME.match(rest) and rest.lower() not in ("início", "prólogo", "epílogo", "fim", "sobre"):
            names[k] = rest
    counts = Counter(names.values())
    pov = {k: n for k, n in names.items() if counts[n] >= 2}
    narrators: dict[str, dict] = {}
    by_chapter: dict[int, str] = {}
    if len(set(pov.values())) >= 2:
        for k, n in pov.items():
            nid = n.lower()
            d = narrators.setdefault(nid, {"id": nid, "name": n, "chapters": [], "_v": Counter()})
            d["chapters"].append(k)
            d["_v"].update(per.get(k, Counter()))
            by_chapter[k] = nid
        for d in narrators.values():
            d["gender"] = _gender(d.pop("_v"), d["name"])
    else:
        # 2) 1ª pessoa: narrador/narradora por capítulo
        total = sum(per.values(), Counter())
        first = total["w"] and total["fp"] / total["w"] > 0.025
        base = _gender(total) if first else "?"
        for k in range(len(book.chapters)):
            v = per.get(k, Counter())
            g = base
            if first and v["w"] > 150 and abs(v["F"] - v["M"]) >= 2:
                g = "F" if v["F"] > v["M"] else "M"
            nid = {"F": "narradora", "M": "narrador"}.get(g, "narrador")
            d = narrators.setdefault(nid, {"id": nid, "name": "Narradora" if nid == "narradora" else "Narrador",
                                           "gender": g if g in ("F", "M") else "?", "chapters": []})
            d["chapters"].append(k)
            by_chapter[k] = nid
    out = sorted(narrators.values(), key=lambda d: -len(d["chapters"]))
    return {"narrators": out, "by_chapter": {str(k): v for k, v in by_chapter.items()}}


class NarrationStore:
    DEFAULT = {"enabled": False, "voices": {}}
    VERSION = 2

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
                if data.get("version") != self.VERSION:
                    data = {"enabled": data.get("enabled", False), "voices": {}}
                for k, v in self.DEFAULT.items():
                    data.setdefault(k, v if not isinstance(v, dict) else dict(v))
                self._cache[book.id] = data
            data = self._cache[book.id]
        if "analysis" not in data:
            data["analysis"] = analyze(book)
            data["version"] = self.VERSION
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
        for nid, v in (values.get("voices") or {}).items():
            if v:
                data["voices"][f"{engine}:{nid}"] = v
        self.save(book.id)
        return data


def narrator_voices(data: dict, engine: str, main_voice: str) -> dict:
    """Voz de cada narrador: escolha da pessoa, senão sugestão por gênero (sem repetir)."""
    out, used = {}, set()
    main_g = catalog.gender_of(main_voice)
    for n in data["analysis"]["narrators"]:
        chosen = data["voices"].get(f"{engine}:{n['id']}")
        if chosen and (catalog.find(chosen) or {}).get("engine") == engine:
            out[n["id"]] = chosen
        elif main_voice not in used and n["gender"] in (main_g, "?"):
            out[n["id"]] = main_voice
        else:
            pool = catalog.pool(engine, n["gender"]) if n["gender"] in ("F", "M") else []
            out[n["id"]] = next((v for v in pool if v not in used and v != main_voice), pool[0] if pool else main_voice)
        used.add(out[n["id"]])
    return out


def voice_for(data: dict, book, idx: int, engine: str, main_voice: str) -> str | None:
    if not data.get("enabled"):
        return None
    nid = data["analysis"]["by_chapter"].get(str(book.chapter_of(idx)))
    if not nid:
        return None
    v = narrator_voices(data, engine, main_voice).get(nid)
    return None if not v or v == main_voice else v


def variant(data: dict, engine: str, main_voice: str) -> str:
    if not data.get("enabled"):
        return ""
    blob = json.dumps([data["analysis"]["by_chapter"], narrator_voices(data, engine, main_voice)], sort_keys=True)
    return "-n" + hashlib.sha1(blob.encode()).hexdigest()[:8]
