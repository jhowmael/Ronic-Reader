"""Gera o mesmo trecho com cada narrador e mede a velocidade no seu Mac.

Uso:
    .venv-lab/bin/python generate.py chatterbox
    .venv-lab/bin/python generate.py xtts
Saída: amostras/*.wav e amostras/resultados.jsonl
"""

from __future__ import annotations

import gc
import json
import os
import sys
import time
from pathlib import Path

import soundfile as sf
import torch

HERE = Path(__file__).parent
OUT = HERE / "amostras"
OUT.mkdir(exist_ok=True)
REFS = {p.stem: p for p in sorted((HERE / "refs").glob("*.wav"))}

# Trecho de Dom Casmurro (domínio público): narração, diálogo e pontuação variada.
TEXT = (
    "Uma noite destas, vindo da cidade para o Engenho Novo, encontrei no trem da Central um rapaz aqui do bairro, "
    "que eu conheço de vista e de chapéu. Cumprimentou-me, sentou-se ao pé de mim, falou da Lua e dos ministros, "
    "e acabou recitando-me versos. A viagem era curta, e os versos pode ser que não fossem inteiramente maus."
)


def record(engine: str, voice: str, wav, sr: int, seconds: float, load: float) -> None:
    path = OUT / f"{engine}-{voice}.wav"
    sf.write(path, wav, sr)
    dur = len(wav) / sr
    row = {"engine": engine, "voice": voice, "file": path.name, "audio_s": round(dur, 1),
           "gen_s": round(seconds, 1), "rtf": round(seconds / dur, 2), "load_s": round(load, 1)}
    with open(OUT / "resultados.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(row, flush=True)


def run_chatterbox() -> None:
    from chatterbox.mtl_tts import ChatterboxMultilingualTTS

    device = "mps" if torch.backends.mps.is_available() else "cpu"
    t = time.time()
    try:
        model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    except Exception as exc:  # alguns ops ainda não rodam no MPS
        print("MPS falhou, usando CPU:", exc)
        device = "cpu"
        model = ChatterboxMultilingualTTS.from_pretrained(device=device)
    load = time.time() - t
    print(f"chatterbox carregado em {load:.0f}s no {device}")

    # aquecimento (a 1ª geração inclui compilação de kernels)
    model.generate("Olá.", language_id="pt")

    for name, ref in [("padrao", None), *REFS.items()]:
        t = time.time()
        wav = model.generate(TEXT, language_id="pt", audio_prompt_path=str(ref) if ref else None,
                             exaggeration=0.5, cfg_weight=0.5)
        record(f"chatterbox_{device}", name, wav.squeeze().cpu().numpy(), model.sr, time.time() - t, load)
        gc.collect()


def run_xtts() -> None:
    os.environ["COQUI_TOS_AGREED"] = "1"  # licença CPML: uso não comercial
    from TTS.api import TTS

    t = time.time()
    tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to("cpu")
    load = time.time() - t
    print(f"xtts carregado em {load:.0f}s")
    speakers = tts.speakers or []
    print("vozes prontas:", ", ".join(speakers))
    tts.tts("Olá.", speaker=speakers[0], language="pt")  # aquecimento

    builtin = [s for s in ("Ana Florence", "Gracie Wise", "Damien Black", "Viktor Menelaos") if s in speakers]
    for name in builtin:
        t = time.time()
        wav = tts.tts(TEXT, speaker=name, language="pt")
        record("xtts", name.lower().replace(" ", "_"), wav, 24000, time.time() - t, load)
    for name, ref in REFS.items():
        t = time.time()
        wav = tts.tts(TEXT, speaker_wav=str(ref), language="pt")
        record("xtts", name, wav, 24000, time.time() - t, load)


if __name__ == "__main__":
    {"chatterbox": run_chatterbox, "xtts": run_xtts}[sys.argv[1]]()
