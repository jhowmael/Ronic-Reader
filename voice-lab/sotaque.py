"""Mede o sotaque (Brasil x Portugal) das vozes: um reconhecedor de FONEMAS (wav2vec2 em IPA)
transcreve a frase-teste e contamos as marcas do português do Brasil:
"tia"->tʃia, "de"->dʒi, "disse"->dʒisi, "noites"->noitʃis, "dia"->dʒia (Portugal: t, d, sem o chiado).
"""
import re, sys
from pathlib import Path
import librosa, torch
from transformers import AutoProcessor, AutoModelForCTC

M = "facebook/wav2vec2-lv-60-espeak-cv-ft"
proc = AutoProcessor.from_pretrained(M); model = AutoModelForCTC.from_pretrained(M).eval()
rows = []
for f in sorted(Path(sys.argv[1]).glob("*.wav")):
    audio, _ = librosa.load(f, sr=16000)
    with torch.no_grad():
        ids = model(proc(audio, sampling_rate=16000, return_tensors="pt").input_values).logits.argmax(-1)
    ph = proc.batch_decode(ids)[0].replace(" ", "")
    br = len(re.findall(r"tʃ|dʒ", ph))
    rows.append((f.stem, br, ph))
for name, br, ph in sorted(rows, key=lambda r: (r[0].split("__")[1], r[0])):
    print(f"{name:28s} marcas BR {br}/5  {ph}")
