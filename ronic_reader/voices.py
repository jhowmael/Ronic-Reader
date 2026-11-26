"""Catálogo de vozes do app (painel "Narrador" e elenco de personagens)."""

from __future__ import annotations

# Catálogo do painel "Narrador" e do elenco, organizado por região/sotaque.
# "region" aparece como etiqueta em cada voz; "group" separa a lista.
BR_ONLINE = "Brasil · online"
BR_LOCAL = "Brasil · no seu Mac, sem internet"
OTHER_ONLINE = "Outros sotaques · online (multilíngues)"
PT_ONLINE = "Portugal · online"


def _v(id_, label, gender, desc, engine, group, region):
    return {"id": id_, "label": label, "gender": gender, "engine": engine, "group": group, "region": region,
            "desc": f"{'feminina' if gender == 'F' else 'masculina'} · {desc}"}


EDGE_VOICES = [
    _v("pt-BR-FranciscaNeural", "Francisca", "F", "clara", "edge", BR_ONLINE, "Brasil"),
    _v("pt-BR-ThalitaMultilingualNeural", "Thalita", "F", "expressiva", "edge", BR_ONLINE, "Brasil"),
    _v("pt-BR-AntonioNeural", "Antônio", "M", "grave", "edge", BR_ONLINE, "Brasil"),
    # vozes de outros idiomas que também falam português (com o sotaque de origem)
    _v("en-US-EmmaMultilingualNeural", "Emma", "F", "americana, conversacional", "edge", OTHER_ONLINE, "EUA"),
    _v("en-US-AvaMultilingualNeural", "Ava", "F", "americana, calorosa", "edge", OTHER_ONLINE, "EUA"),
    _v("fr-FR-VivienneMultilingualNeural", "Vivienne", "F", "francesa, suave", "edge", OTHER_ONLINE, "França"),
    _v("en-AU-WilliamMultilingualNeural", "William", "M", "australiano, firme", "edge", OTHER_ONLINE, "Austrália"),
    _v("en-US-AndrewMultilingualNeural", "Andrew", "M", "americano, conversacional", "edge", OTHER_ONLINE, "EUA"),
    _v("en-US-BrianMultilingualNeural", "Brian", "M", "americano, leve", "edge", OTHER_ONLINE, "EUA"),
    _v("fr-FR-RemyMultilingualNeural", "Rémy", "M", "francês, calmo", "edge", OTHER_ONLINE, "França"),
    _v("it-IT-GiuseppeMultilingualNeural", "Giuseppe", "M", "italiano, expressivo", "edge", OTHER_ONLINE, "Itália"),
    _v("pt-PT-DuarteNeural", "Duarte", "M", "português de Portugal", "edge", PT_ONLINE, "Portugal"),
]
# Kokoro (offline): todas falam com fonemas do português do Brasil; a ordem segue o sotaque
# brasileiro medido no voice-lab (sotaque.py). Dora e Clara saíram: puxavam para Portugal.
LOCAL_VOICES = [
    _v("if_sara", "Sara", "F", "sotaque brasileiro, leve", "kokoro", BR_LOCAL, "Brasil"),
    _v("bf_isabella", "Isabela", "F", "sotaque brasileiro, firme", "kokoro", BR_LOCAL, "Brasil"),
    _v("af_bella", "Bella", "F", "sotaque brasileiro, calorosa", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pf_dora*0.6+bf_emma*0.4", "Helena", "F", "sotaque brasileiro, suave", "kokoro", BR_LOCAL, "Brasil"),
    _v("im_nicola", "Nicolau", "M", "sotaque brasileiro, firme", "kokoro", BR_LOCAL, "Brasil"),
    _v("bm_george", "George", "M", "sotaque brasileiro, maduro", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_santa*0.6+am_onyx*0.4", "Otávio", "M", "sotaque brasileiro, grave", "kokoro", BR_LOCAL, "Brasil"),
    _v("pm_santa", "Santa", "M", "sotaque brasileiro", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_alex*0.6+am_michael*0.4", "Miguel", "M", "sotaque brasileiro", "kokoro", BR_LOCAL, "Brasil"),
    _v("pm_alex", "Alex", "M", "sotaque brasileiro", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_alex*0.6+bm_george*0.4", "Jorge", "M", "sotaque brasileiro, firme", "kokoro", BR_LOCAL, "Brasil"),
]
DEFAULT_VOICE = {"edge": "pt-BR-FranciscaNeural", "kokoro": "if_sara", "piper": "pt_BR-faber-medium"}


def catalog() -> list[dict]:
    return EDGE_VOICES + LOCAL_VOICES


def find(voice_id: str | None) -> dict | None:
    return next((v for v in catalog() if v["id"] == voice_id), None)


def gender_of(voice_id: str | None) -> str:
    v = find(voice_id)
    return v.get("gender", "?") if v else "?"


def pool(engine: str, gender: str) -> list[str]:
    """Vozes de um motor e gênero, na ordem do catálogo (as mais claras primeiro)."""
    return [v["id"] for v in catalog() if v["engine"] == engine and v.get("gender") == gender]
