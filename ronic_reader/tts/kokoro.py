"""Motor Kokoro-82M: voz neural pequena (Apache 2.0) que roda 100% offline e rápido.

- Vozes pt-BR prontas: pf_dora (feminina), pm_alex e pm_santa (masculinas).
- Pronúncia muito nítida; gera mais rápido que o tempo real até na CPU.
- O modelo (~340 MB) é baixado uma vez para ~/.local/share/ronic-reader/kokoro.
"""

from __future__ import annotations

import os
import re
import threading
import urllib.request
import wave
from pathlib import Path

import numpy as np

from ..splitter import split_sentences

DEFAULT_VOICE = "if_sara"
VOICES = ("if_sara", "pm_santa", "pm_alex")
MODELS_DIR = Path(os.environ.get("RONIC_KOKORO_DIR", Path.home() / ".local/share/ronic-reader/kokoro"))
FILES = {
    "kokoro-v1.0.onnx": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx",
    "voices-v1.0.bin": "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin",
}
SENTENCE_PAUSE = 0.18
PARAGRAPH_PAUSE = 0.5


def _percent(value: str) -> int:
    m = re.fullmatch(r"\s*([+-]?\d+)\s*%?\s*", value or "+0%")
    return int(m.group(1)) if m else 0


def ensure_models(directory: Path = MODELS_DIR) -> tuple[Path, Path]:
    """Baixa o modelo na primeira vez (download atômico: nunca deixa arquivo pela metade)."""
    directory.mkdir(parents=True, exist_ok=True)
    for name, url in FILES.items():
        target = directory / name
        if target.exists() and target.stat().st_size > 1_000_000:
            continue
        print(f"  Baixando o modelo de voz Kokoro ({name}) — só na primeira vez…", flush=True)
        tmp = target.with_suffix(target.suffix + ".part")
        with urllib.request.urlopen(url, timeout=60) as resp, open(tmp, "wb") as fh:
            while block := resp.read(1 << 20):
                fh.write(block)
        os.replace(tmp, target)
    return directory / "kokoro-v1.0.onnx", directory / "voices-v1.0.bin"


_MODEL = None
_MODEL_LOCK = threading.Lock()  # carregar uma vez
_INFER_LOCK = threading.Lock()  # o modelo não é thread-safe: uma frase por vez


def shared_model():
    """Um único modelo na memória para todas as vozes: trocar de voz não recarrega nada."""
    global _MODEL
    with _MODEL_LOCK:
        if _MODEL is None:
            from kokoro_onnx import Kokoro

            model, voices = ensure_models()
            _MODEL = Kokoro(str(model), str(voices))
        return _MODEL


def resolve_style(kokoro, voice: str | None):
    """'pf_dora' ou uma mistura 'mix:pf_dora*0.6+af_heart*0.4' -> nome ou vetor de estilo."""
    voice = voice or DEFAULT_VOICE
    if not voice.startswith("mix:"):
        return voice
    style = None
    for term in voice[4:].split("+"):
        name, _, weight = term.partition("*")
        vec = kokoro.get_voice_style(name.strip()) * float(weight or 1)
        style = vec if style is None else style + vec
    return style


# --------------------------------------------------------------------------- #
# Fonemas com o sotaque do Brasil.
# O espeak-ng (pt-br) escreve o "e" e o "a" finais átonos como "y" e "æ", e o
# Kokoro os pronuncia abafados, como em Portugal ("dɨ", "noitɨʃ"). Trocando por
# "i" e "ɐ" ("dʒi", "noitʃis"), as marcas brasileiras medidas pelo reconhecedor de
# fonemas (voice-lab/sotaque.py) subiram de 57 para 67 em 13 vozes.
# --------------------------------------------------------------------------- #
_TOKENIZER = None
_TOK_LOCK = threading.Lock()


def phonemize_ptbr(text: str) -> str:
    global _TOKENIZER
    with _TOK_LOCK:
        if _TOKENIZER is None:
            from kokoro_onnx.tokenizer import Tokenizer

            _TOKENIZER = Tokenizer()
        ph = _TOKENIZER.phonemize(text, "pt-br")
    return ph.replace("y", "i").replace("æ", "ɐ")


class KokoroEngine:
    def __init__(self, voice: str | None = None, rate: str = "+0%", volume: str = "+0%", **_ignored):
        self.kokoro = shared_model()
        self.voice = voice or DEFAULT_VOICE
        self._styles: dict[str, object] = {}
        self.speed = min(2.0, max(0.5, 1 + _percent(rate) / 100))
        self.gain = min(2.0, max(0.3, 1 + _percent(volume) / 100))
        try:
            import lameenc  # noqa: F401

            self.extension = ".mp3"
        except ImportError:
            self.extension = ".wav"

    def _style(self, voice: str | None):
        key = voice or self.voice
        if key not in self._styles:
            self._styles[key] = resolve_style(self.kokoro, key)
        return self._styles[key]

    def _speak(self, text: str, voice: str | None = None) -> tuple[np.ndarray, int]:
        with _INFER_LOCK:
            samples, sr = self.kokoro.create(phonemize_ptbr(text), voice=self._style(voice), speed=self.speed,
                                             lang="pt-br", is_phonemes=True)
        return np.asarray(samples, dtype=np.float32) * self.gain, sr

    def synthesize_part(self, chunks: list[str], out_path: Path, label: str = "") -> list[tuple[float, float, str]]:
        return self.synthesize_parts([(None, c) for c in chunks], out_path)

    def synthesize_parts(self, parts: list[tuple[str | None, str]], out_path: Path, should_stop=None, wait_turn=None) -> list:
        pieces: list[np.ndarray] = []
        cues: list[tuple[float, float, str]] = []
        sr, t = 24000, 0.0
        for voice, chunk in parts:
            for para in chunk.split("\n\n"):
                for sentence in split_sentences(para) or [para]:
                    if wait_turn:
                        wait_turn()  # pedidos de play passam na frente da pré-geração
                    if should_stop and should_stop():
                        return []
                    audio, sr = self._speak(sentence, voice)
                    dur = len(audio) / sr
                    cues.append((t, t + dur, sentence))
                    pieces += [audio, np.zeros(int(sr * SENTENCE_PAUSE), np.float32)]
                    t += dur + SENTENCE_PAUSE
                pieces.append(np.zeros(int(sr * PARAGRAPH_PAUSE), np.float32))
                t += PARAGRAPH_PAUSE

        pcm = (np.clip(np.concatenate(pieces) if pieces else np.zeros(0, np.float32), -1, 1) * 32767).astype(np.int16)
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        if self.extension == ".mp3":
            import lameenc

            enc = lameenc.Encoder()
            enc.set_bit_rate(64)
            enc.set_in_sample_rate(sr)
            enc.set_channels(1)
            enc.set_quality(2)
            tmp.write_bytes(enc.encode(pcm.tobytes()) + enc.flush())
        else:
            with wave.open(str(tmp), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(sr)
                w.writeframes(pcm.tobytes())
        os.replace(tmp, out_path)
        return cues
