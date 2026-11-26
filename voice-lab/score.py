"""Mede a CLAREZA de cada amostra: um reconhecedor de fala (Whisper, local) transcreve
o áudio e comparamos com o texto original. Menos palavras erradas = pronúncia mais nítida.

Uso: .venv-lab/bin/python score.py   -> amostras/clareza.json
"""

import json
import re
import unicodedata
from pathlib import Path

import jiwer
from faster_whisper import WhisperModel

HERE = Path(__file__).parent
OUT = HERE / "amostras"
TEXT = (HERE / "texto.txt").read_text(encoding="utf-8")


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKC", s.lower())
    s = re.sub(r"[-–—]", " ", s)
    s = re.sub(r"[^\w\s]", "", s)
    return " ".join(s.split())


model = WhisperModel("small", device="cpu", compute_type="int8")
ref = norm(TEXT)
scores = {}
for f in sorted(OUT.glob("*.*")):
    if f.suffix not in (".wav", ".mp3"):
        continue
    segments, _ = model.transcribe(str(f), language="pt", beam_size=5, vad_filter=False)
    hyp = norm(" ".join(s.text for s in segments))
    wer = jiwer.wer(ref, hyp)
    scores[f.name] = {"wer": round(wer, 3), "clareza": round(max(0.0, 1 - wer) * 100, 1), "transcricao": hyp}
    print(f"{f.name:45s} clareza {scores[f.name]['clareza']:5.1f}%")
(OUT / "clareza.json").write_text(json.dumps(scores, ensure_ascii=False, indent=1), encoding="utf-8")
