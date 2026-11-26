"""Motor Piper: voz neural que roda 100% offline, direto na sua CPU.

- Sem internet (depois de baixar o modelo uma única vez, ~60 MB).
- Voz em pt-BR recomendada: "pt_BR-faber-medium" (masculina).
  Outras: veja https://huggingface.co/rhasspy/piper-voices/tree/main/pt/pt_BR
- Gera MP3 com o encoder `lameenc` (se instalado) ou WAV caso contrário.
"""

from __future__ import annotations

import os
import re
import wave
from pathlib import Path

import numpy as np

from ..splitter import split_sentences

DEFAULT_VOICE = "pt_BR-faber-medium"
DEFAULT_MODELS_DIR = Path(os.environ.get("RONIC_MODELS_DIR", Path.home() / ".local/share/ronic-reader/piper"))

SENTENCE_PAUSE = 0.25  # segundos de silêncio entre frases
PARAGRAPH_PAUSE = 0.6  # segundos de silêncio entre parágrafos


def _percent(value: str) -> int:
    m = re.fullmatch(r"\s*([+-]?\d+)\s*%?\s*", value or "+0%")
    return int(m.group(1)) if m else 0


def _rate_to_length_scale(rate: str) -> float:
    """Converte "+20%" (estilo edge-tts) para o length_scale do Piper (menor = mais rápido)."""
    return 1.0 / max(0.3, 1 + _percent(rate) / 100)


def ensure_model(voice: str, models_dir: Path = DEFAULT_MODELS_DIR) -> Path:
    """Devolve o caminho do .onnx, baixando o modelo na primeira vez se necessário."""
    as_path = Path(voice).expanduser()
    if as_path.suffix == ".onnx" and as_path.exists():
        return as_path

    model = models_dir / f"{voice}.onnx"
    if not model.exists():
        from piper.download_voices import download_voice

        print(f"  Baixando voz Piper '{voice}' para {models_dir} (só na primeira vez)...")
        models_dir.mkdir(parents=True, exist_ok=True)
        download_voice(voice, models_dir)
    return model


class PiperEngine:
    def __init__(
        self,
        voice: str | None = None,
        rate: str = "+0%",
        volume: str = "+0%",
        expressiveness: float = 0.667,
        models_dir: Path | None = None,
        **_ignored,
    ):
        from piper import PiperVoice
        from piper.config import SynthesisConfig

        self.voice_name = voice or DEFAULT_VOICE
        model = ensure_model(self.voice_name, models_dir or DEFAULT_MODELS_DIR)
        self.voice = PiperVoice.load(model)
        self.sample_rate = self.voice.config.sample_rate
        self.syn_config = SynthesisConfig(
            length_scale=_rate_to_length_scale(rate),  # velocidade
            volume=1 + _percent(volume) / 100,  # intensidade
            noise_scale=expressiveness,  # variação de entonação (mais = mais "viva")
            noise_w_scale=0.5 + expressiveness * 0.5,  # variação de ritmo entre fonemas
            normalize_audio=True,
        )

        try:
            import lameenc  # noqa: F401

            self.extension = ".mp3"
        except ImportError:
            self.extension = ".wav"

    def _speak(self, text: str) -> np.ndarray:
        arrays = [c.audio_int16_array for c in self.voice.synthesize(text, self.syn_config)]
        return np.concatenate(arrays) if arrays else np.zeros(0, dtype=np.int16)

    def synthesize_part(self, chunks: list[str], out_path: Path, label: str = "") -> list[tuple[float, float, str]]:
        sr = self.sample_rate
        pieces: list[np.ndarray] = []
        cues: list[tuple[float, float, str]] = []
        t = 0.0

        def silence(seconds: float) -> np.ndarray:
            return np.zeros(int(sr * seconds), dtype=np.int16)

        for i, chunk in enumerate(chunks, 1):
            print(f"\r    {label} bloco {i}/{len(chunks)}", end="", flush=True)
            for para in chunk.split("\n\n"):
                # sintetiza frase a frase para gerar legendas sincronizadas
                for sentence in split_sentences(para):
                    audio = self._speak(sentence)
                    dur = len(audio) / sr
                    cues.append((t, t + dur, sentence))
                    pieces += [audio, silence(SENTENCE_PAUSE)]
                    t += dur + SENTENCE_PAUSE
                pieces.append(silence(PARAGRAPH_PAUSE))
                t += PARAGRAPH_PAUSE
        print()

        pcm = np.concatenate(pieces) if pieces else np.zeros(0, dtype=np.int16)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        if self.extension == ".mp3":
            import lameenc

            enc = lameenc.Encoder()
            enc.set_bit_rate(64)
            enc.set_in_sample_rate(sr)
            enc.set_channels(1)
            enc.set_quality(2)  # 2 = alta qualidade
            tmp.write_bytes(enc.encode(pcm.tobytes()) + enc.flush())
        else:
            with wave.open(str(tmp), "wb") as wav:
                wav.setnchannels(1)
                wav.setsampwidth(2)
                wav.setframerate(sr)
                wav.writeframes(pcm.tobytes())
        os.replace(tmp, out_path)
        return cues
