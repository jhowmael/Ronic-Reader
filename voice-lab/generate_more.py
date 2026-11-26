"""Mais narradores para comparar (roda no ambiente principal do app: ../.venv).

- Microsoft multilíngues (edge-tts, grátis, online): vozes "conversacionais" que falam português.
- Kokoro-82M (offline, leve, Apache 2.0): vozes pt-BR prontas, pronúncia bem nítida.
- macOS (offline, nativas do sistema).

Uso: ../.venv/bin/python generate_more.py
"""

from __future__ import annotations

import asyncio
import json
import subprocess
import tempfile
import time
import wave
from pathlib import Path

import numpy as np

HERE = Path(__file__).parent
OUT = HERE / "amostras"
OUT.mkdir(exist_ok=True)
TEXT = (HERE / "texto.txt").read_text(encoding="utf-8").strip()

EDGE = [
    "en-US-AndrewMultilingualNeural", "en-US-AvaMultilingualNeural", "en-US-BrianMultilingualNeural",
    "en-US-EmmaMultilingualNeural", "en-AU-WilliamMultilingualNeural", "fr-FR-VivienneMultilingualNeural",
    "fr-FR-RemyMultilingualNeural", "it-IT-GiuseppeMultilingualNeural",
    "pt-BR-FranciscaNeural", "pt-BR-AntonioNeural",
]
KOKORO = ["pf_dora", "pm_alex", "pm_santa"]
MACOS = ["Luciana"]


def record(engine: str, voice: str, file: Path, audio_s: float, gen_s: float, offline: bool) -> None:
    row = {"engine": engine, "voice": voice, "file": file.name, "audio_s": round(audio_s, 1),
           "gen_s": round(gen_s, 1), "rtf": round(gen_s / max(audio_s, 0.1), 2), "offline": offline}
    with open(OUT / "resultados.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(row, flush=True)


def write_wav(path: Path, samples: np.ndarray, sr: int) -> None:
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1)
        w.setsampwidth(2)
        w.setframerate(sr)
        w.writeframes(pcm.tobytes())


async def run_edge() -> None:
    import edge_tts

    for voice in EDGE:
        path = OUT / f"edge-{voice}.mp3"
        t = time.time()
        try:
            await edge_tts.Communicate(TEXT, voice).save(str(path))
        except Exception as exc:
            print("falhou", voice, exc)
            continue
        record("edge", voice, path, path.stat().st_size / 6000, time.time() - t, offline=False)


def run_kokoro() -> None:
    from kokoro_onnx import Kokoro

    models = HERE / "models/kokoro"
    t = time.time()
    k = Kokoro(str(models / "kokoro-v1.0.onnx"), str(models / "voices-v1.0.bin"))
    print(f"kokoro carregado em {time.time() - t:.1f}s")
    for voice in KOKORO:
        t = time.time()
        samples, sr = k.create(TEXT, voice=voice, speed=1.0, lang="pt-br")
        path = OUT / f"kokoro-{voice}.wav"
        write_wav(path, samples, sr)
        record("kokoro", voice, path, len(samples) / sr, time.time() - t, offline=True)


def run_macos() -> None:
    for voice in MACOS:
        with tempfile.TemporaryDirectory() as tmp:
            aiff = Path(tmp) / "a.aiff"
            t = time.time()
            subprocess.run(["say", "-v", voice, "-o", str(aiff), TEXT], check=True)
            gen = time.time() - t
            path = OUT / f"macos-{voice}.wav"
            subprocess.run(["afconvert", "-f", "WAVE", "-d", "LEI16@24000", str(aiff), str(path)], check=True)
        with wave.open(str(path)) as w:
            dur = w.getnframes() / w.getframerate()
        record("macos", voice, path, dur, gen, offline=True)


if __name__ == "__main__":
    asyncio.run(run_edge())
    run_kokoro()
    run_macos()
