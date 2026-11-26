"""Motores de voz disponíveis.

Todos seguem a mesma interface (`synthesize_part`) para que trocar de motor seja
só mudar `--engine edge` por `--engine piper`.
"""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

#: Legenda: (início_em_segundos, fim_em_segundos, texto)
Cue = tuple[float, float, str]


class TTSEngine(Protocol):
    #: extensão do arquivo gerado (".mp3" ou ".wav")
    extension: str

    def synthesize_part(self, chunks: list[str], out_path: Path, label: str = "") -> list[Cue]:
        """Gera o áudio de uma parte inteira e devolve as legendas (cues)."""
        ...


def get_engine(name: str, **options) -> TTSEngine:
    if name == "edge":
        from .edge import EdgeEngine

        return EdgeEngine(**options)
    if name == "kokoro":
        from .kokoro import KokoroEngine

        return KokoroEngine(**options)
    if name == "piper":
        from .piper import PiperEngine

        return PiperEngine(**options)
    raise ValueError(f"Motor de voz desconhecido: {name!r} (use 'edge', 'kokoro' ou 'piper')")
