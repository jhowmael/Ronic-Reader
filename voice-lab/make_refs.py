"""Recorta ~15 s de narração limpa de cada gravação do LibriVox (domínio público).

As gravações começam com o aviso padrão do LibriVox, então pulamos o primeiro minuto.
Uso: .venv-lab/bin/python make_refs.py
"""

from pathlib import Path

import librosa
import numpy as np
import soundfile as sf

HERE = Path(__file__).parent
CLIPS = {
    # arquivo bruto                              -> (nome do narrador, início em segundos)
    "o_alienista_0904_librivox.mp3": ("leni", 75),
    "cinco_minutos_vcf_librivox.mp3": ("vicente", 75),
    "triste_fim_policarpo_quaresma_fm_librivox.mp3": ("miramontes", 75),
}
SR = 24000
LENGTH = 15.0

for raw, (name, start) in CLIPS.items():
    audio, _ = librosa.load(HERE / "refs/raw" / raw, sr=SR, mono=True, offset=start, duration=LENGTH + 4)
    # começa e termina em silêncio (evita cortar palavra no meio)
    frame = int(0.03 * SR)
    energy = np.array([np.sqrt(np.mean(audio[i:i + frame] ** 2)) for i in range(0, len(audio) - frame, frame)])
    quiet = np.where(energy < np.percentile(energy, 20))[0] * frame
    a = next((q for q in quiet if q > 0), 0)
    b = next((q for q in quiet[::-1] if q - a <= LENGTH * SR), len(audio))
    clip = audio[a:b]
    clip = clip / (np.max(np.abs(clip)) + 1e-9) * 0.9
    out = HERE / "refs" / f"{name}.wav"
    sf.write(out, clip, SR)
    print(f"{out.name}: {len(clip) / SR:.1f} s")
