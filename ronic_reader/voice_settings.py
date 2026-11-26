"""Calibragem da voz: predefinições, validação dos ajustes e preferências salvas.

Ordem de prioridade de cada ajuste (do mais forte para o mais fraco):
    opção na linha de comando  >  --preset  >  config salva (--save-config)  >  padrão
"""

from __future__ import annotations

import json
import os
import re
from dataclasses import asdict, dataclass, fields
from pathlib import Path

CONFIG_PATH = Path(os.environ.get("RONIC_CONFIG", Path.home() / ".config/ronic-reader/config.json"))


@dataclass
class VoiceSettings:
    engine: str = "edge"
    voice: str | None = None  # None = voz padrão do motor
    rate: str = "+0%"  # velocidade: -50% (lento) .. +100% (rápido)
    volume: str = "+0%"  # intensidade/volume: -50% .. +50%   (edge e piper)
    pitch: str = "+0Hz"  # tom: -50Hz (grave) .. +50Hz (agudo) (só edge)
    expressiveness: float = 0.667  # variação da entonação no Piper: 0 (monótono) .. 1 (expressivo)


# Atalhos para não precisar digitar o nome completo da voz (edge-tts)
VOICE_ALIASES = {
    "francisca": "pt-BR-FranciscaNeural",
    "antonio": "pt-BR-AntonioNeural",
    "antônio": "pt-BR-AntonioNeural",
    "thalita": "pt-BR-ThalitaMultilingualNeural",
    "raquel": "pt-PT-RaquelNeural",
    "duarte": "pt-PT-DuarteNeural",
}

# Predefinições prontas para diferentes usos.
PRESETS: dict[str, dict[str, object]] = {
    "natural": {"rate": "+0%", "pitch": "+0Hz", "volume": "+0%", "expressiveness": 0.667},
    "narrador": {"rate": "-5%", "pitch": "-2Hz", "volume": "+0%", "expressiveness": 0.75},
    "calmo": {"rate": "-12%", "pitch": "-4Hz", "volume": "-5%", "expressiveness": 0.5},
    "dinamico": {"rate": "+12%", "pitch": "+3Hz", "volume": "+5%", "expressiveness": 0.85},
    "estudo": {"rate": "+30%", "pitch": "+0Hz", "volume": "+0%", "expressiveness": 0.6},
}
PRESET_HELP = {
    "natural": "neutro, como a voz foi treinada",
    "narrador": "um pouco mais lento e grave, bom para audiolivros",
    "calmo": "lento e suave, para relaxar/dormir",
    "dinamico": "mais rápido e animado",
    "estudo": "bem rápido, para revisar conteúdo",
}


def _signed(value: str | int | float, unit: str, lo: int, hi: int, name: str) -> str:
    """Aceita "10", "+10", "10%", "-5Hz" e devolve no formato do edge-tts ("+10%")."""
    s = str(value).strip().replace(" ", "").lower().removesuffix(unit.lower())
    if not re.fullmatch(r"[+-]?\d+", s):
        raise ValueError(f"{name} inválido: {value!r} (ex.: +10{unit} ou -5{unit})")
    n = int(s)
    if not lo <= n <= hi:
        raise ValueError(f"{name} fora do intervalo {lo}{unit}..+{hi}{unit}: {value!r}")
    return f"{n:+d}{unit}"


def normalize_rate(v) -> str:
    return _signed(v, "%", -50, 100, "Velocidade")


def normalize_volume(v) -> str:
    return _signed(v, "%", -50, 50, "Volume")


def normalize_pitch(v) -> str:
    return _signed(v, "Hz", -50, 50, "Tom")


def normalize_expressiveness(v) -> float:
    x = float(v)
    if not 0 <= x <= 1:
        raise ValueError(f"Expressividade deve estar entre 0 e 1: {v!r}")
    return x


def load_config(path: Path = CONFIG_PATH) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    names = {f.name for f in fields(VoiceSettings)}
    return {k: v for k, v in data.items() if k in names}


def save_config(settings: VoiceSettings, path: Path = CONFIG_PATH) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(asdict(settings), indent=2, ensure_ascii=False), encoding="utf-8")
    return path


def resolve_settings(cli: dict, preset: str | None, config: dict | None = None) -> VoiceSettings:
    """Combina opções da CLI, predefinição e config salva, validando tudo."""
    merged: dict = {}
    merged.update(config if config is not None else load_config())
    if preset:
        if preset not in PRESETS:
            raise ValueError(f"Predefinição desconhecida: {preset!r}. Opções: {', '.join(PRESETS)}")
        merged.update(PRESETS[preset])
    merged.update({k: v for k, v in cli.items() if v is not None})

    s = VoiceSettings(**{k: v for k, v in merged.items() if k in {f.name for f in fields(VoiceSettings)}})
    s.rate = normalize_rate(s.rate)
    s.volume = normalize_volume(s.volume)
    s.pitch = normalize_pitch(s.pitch)
    s.expressiveness = normalize_expressiveness(s.expressiveness)
    if s.voice and s.voice.lower() in VOICE_ALIASES:
        s.voice = VOICE_ALIASES[s.voice.lower()]
    # Voz de um motor não existe no outro: volta para a voz padrão do motor escolhido.
    if s.engine not in ENGINES:
        raise ValueError(f"Motor de voz desconhecido: {s.engine!r} (use {', '.join(ENGINES)})")
    if s.voice and engine_of_voice(s.voice) != s.engine:
        s.voice = None
    return s


ENGINES = ("edge", "kokoro", "piper")


def engine_of_voice(voice: str) -> str:
    """'pt-BR-FranciscaNeural' -> edge · 'pf_dora' -> kokoro · 'pt_BR-faber-medium' -> piper."""
    if re.fullmatch(r"[a-z]{2}_[A-Z]{2}-.+", voice) or voice.endswith(".onnx"):
        return "piper"
    if re.fullmatch(r"[a-z]{2}_[a-z]+", voice) or voice.startswith("mix:"):
        return "kokoro"
    return "edge"


def describe(s: VoiceSettings) -> str:
    voice = s.voice or {"edge": "pt-BR-FranciscaNeural", "kokoro": "if_sara"}.get(s.engine, "pt_BR-faber-medium")
    extra = {"edge": f"tom {s.pitch}", "piper": f"expressividade {s.expressiveness:.2f}"}.get(s.engine, "offline")
    return f"{s.engine} | {voice} | velocidade {s.rate} | volume {s.volume} | {extra}"
