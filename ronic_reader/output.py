"""Arquivos de saída: nomes seguros, legendas .srt, playlist .m3u e junção de partes."""

from __future__ import annotations

import re
import unicodedata
import wave
from pathlib import Path


def safe_filename(title: str, max_len: int = 60) -> str:
    """Transforma "Capítulo 3: O Início?" em "Capitulo 3 - O Inicio" (seguro em qualquer SO)."""
    s = unicodedata.normalize("NFKD", title).encode("ascii", "ignore").decode()
    s = re.sub(r"[:/\\|]+", " - ", s)
    s = re.sub(r"[^\w\s.,()\-]", "", s)
    s = re.sub(r"\s+", " ", s).strip(" .-")
    return (s[:max_len].rstrip(" .-") or "parte")


def _srt_time(seconds: float) -> str:
    ms = int(round(seconds * 1000))
    h, ms = divmod(ms, 3_600_000)
    m, ms = divmod(ms, 60_000)
    s, ms = divmod(ms, 1000)
    return f"{h:02}:{m:02}:{s:02},{ms:03}"


def write_srt(cues: list[tuple[float, float, str]], path: Path) -> None:
    lines = []
    for i, (start, end, text) in enumerate(cues, 1):
        lines += [str(i), f"{_srt_time(start)} --> {_srt_time(end)}", text.strip(), ""]
    path.write_text("\n".join(lines), encoding="utf-8")


def write_playlist(files: list[Path], path: Path) -> None:
    """Playlist .m3u: abre todas as partes na ordem certa em qualquer player."""
    path.write_text("#EXTM3U\n" + "\n".join(f.name for f in files) + "\n", encoding="utf-8")


def merge_audio(files: list[Path], out_path: Path) -> None:
    """Junta todas as partes em um único arquivo."""
    if out_path.suffix == ".wav":
        with wave.open(str(out_path), "wb") as dst:
            for i, f in enumerate(files):
                with wave.open(str(f), "rb") as src:
                    if i == 0:
                        dst.setparams(src.getparams())
                    dst.writeframes(src.readframes(src.getnframes()))
        return
    # MP3: os quadros podem ser concatenados diretamente (mesmo formato em todas as partes)
    with open(out_path, "wb") as dst:
        for f in files:
            dst.write(f.read_bytes())
