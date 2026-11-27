"""Catálogo de vozes do app (painel "Narrador" e elenco de personagens)."""

from __future__ import annotations

# Catálogo do painel "Narrador": só vozes com sotaque do Brasil.
# "region" aparece como etiqueta em cada voz; "group" separa a lista.
BR_ONLINE = "Brasil · online"
BR_LOCAL = "Brasil · no seu Mac, sem internet"


def _v(id_, label, gender, desc, engine, group, region):
    return {"id": id_, "label": label, "gender": gender, "engine": engine, "group": group, "region": region,
            "desc": f"{'feminina' if gender == 'F' else 'masculina'} · {desc}"}


EDGE_VOICES = [
    _v("pt-BR-FranciscaNeural", "Francisca", "F", "clara", "edge", BR_ONLINE, "Brasil"),
    _v("pt-BR-ThalitaMultilingualNeural", "Thalita", "F", "expressiva", "edge", BR_ONLINE, "Brasil"),
    _v("pt-BR-AntonioNeural", "Antônio", "M", "grave", "edge", BR_ONLINE, "Brasil"),
]
# Kokoro (offline): todas falam com fonemas do português do Brasil; a ordem segue o sotaque
# brasileiro medido no voice-lab (sotaque.py). Dora e Clara saíram: puxavam para Portugal.
LOCAL_VOICES = [
    _v("if_sara", "Sara", "F", "leve", "kokoro", BR_LOCAL, "Brasil"),
    _v("bf_isabella", "Isabela", "F", "firme", "kokoro", BR_LOCAL, "Brasil"),
    _v("af_bella", "Bella", "F", "calorosa", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pf_dora*0.6+bf_emma*0.4", "Helena", "F", "suave", "kokoro", BR_LOCAL, "Brasil"),
    _v("im_nicola", "Nicolau", "M", "firme", "kokoro", BR_LOCAL, "Brasil"),
    _v("bm_george", "George", "M", "maduro", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_santa*0.6+am_onyx*0.4", "Otávio", "M", "grave", "kokoro", BR_LOCAL, "Brasil"),
    _v("pm_santa", "Santa", "M", "natural", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_alex*0.6+am_michael*0.4", "Miguel", "M", "natural", "kokoro", BR_LOCAL, "Brasil"),
    _v("pm_alex", "Alex", "M", "natural", "kokoro", BR_LOCAL, "Brasil"),
    _v("mix:pm_alex*0.6+bm_george*0.4", "Jorge", "M", "firme", "kokoro", BR_LOCAL, "Brasil"),
]
NATIVE_BR = ("pm_santa", "pm_alex")
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
    ids = [v["id"] for v in catalog() if v["engine"] == engine and v.get("gender") == gender]
    # narradores sugeridos: primeiro as vozes brasileiras nativas (sem sotaque, medido no voice-lab)
    return sorted(ids, key=lambda i: i not in NATIVE_BR)
