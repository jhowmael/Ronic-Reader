"""Candidatas a novas vozes Kokoro em português (roda no ambiente do app: ../.venv).

O Kokoro tem só 3 vozes nativas pt-BR. Testamos:
- vozes de outros idiomas falando português (a pronúncia vem do português; o timbre, da voz);
- misturas: 60% de uma voz pt-BR + 40% de outra, que mantém o sotaque brasileiro com outro timbre.
"""

import json
import time
import wave
from pathlib import Path

import numpy as np
from kokoro_onnx import Kokoro

HERE = Path(__file__).parent
OUT = HERE / "amostras"
TEXT = (HERE / "texto.txt").read_text(encoding="utf-8").strip()

SINGLE = ["ef_dora", "em_alex", "em_santa", "if_sara", "im_nicola", "ff_siwis", "af_heart", "af_bella", "af_nicole",
          "af_sarah", "af_kore", "af_aoede", "am_michael", "am_fenrir", "am_puck", "am_onyx", "bf_emma", "bf_isabella",
          "bm_george", "bm_fable", "bm_lewis"]
MIXES = [("pf_dora", "af_heart"), ("pf_dora", "af_bella"), ("pf_dora", "if_sara"), ("pf_dora", "bf_emma"),
         ("pf_dora", "ef_dora"), ("pf_dora", "ff_siwis"), ("pm_alex", "am_michael"), ("pm_alex", "am_fenrir"),
         ("pm_alex", "bm_george"), ("pm_alex", "im_nicola"), ("pm_santa", "am_onyx"), ("pm_santa", "bm_fable"),
         ("pm_santa", "em_santa")]

k = Kokoro(str(HERE / "models/kokoro/kokoro-v1.0.onnx"), str(HERE / "models/kokoro/voices-v1.0.bin"))


def save(name: str, voice, label: str) -> None:
    t = time.time()
    samples, sr = k.create(TEXT, voice=voice, speed=1.0, lang="pt-br")
    gen = time.time() - t
    path = OUT / f"kokorox-{name}.wav"
    pcm = (np.clip(samples, -1, 1) * 32767).astype(np.int16)
    with wave.open(str(path), "wb") as w:
        w.setnchannels(1); w.setsampwidth(2); w.setframerate(sr); w.writeframes(pcm.tobytes())
    row = {"engine": "kokoro", "voice": label, "file": path.name, "audio_s": round(len(samples) / sr, 1),
           "gen_s": round(gen, 1), "rtf": round(gen / (len(samples) / sr), 2), "offline": True}
    with open(OUT / "resultados.jsonl", "a") as fh:
        fh.write(json.dumps(row) + "\n")
    print(row, flush=True)


for v in SINGLE:
    save(v, v, v)
for a, b in MIXES:
    style = k.get_voice_style(a) * 0.6 + k.get_voice_style(b) * 0.4
    save(f"{a}+{b}", style, f"mix:{a}*0.6+{b}*0.4")
