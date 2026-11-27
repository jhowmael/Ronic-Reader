"""Motor edge-tts: vozes neurais da Microsoft (as mesmas do Edge "Ler em voz alta").

- Gratuito, sem chave de API e sem cobrança por caractere.
- Precisa de internet durante a geração do áudio (o texto é enviado ao serviço
  de leitura do Edge). Para algo 100% offline, use o motor Piper.
"""

from __future__ import annotations

import asyncio
import os
import random
from pathlib import Path

import aiohttp
import edge_tts
from edge_tts.exceptions import EdgeTTSException
import edge_tts.communicate as _edge_comm


def _ssml_ptbr(tc, escaped_text) -> str:
    """SSML sempre em português do Brasil. O edge-tts manda xml:lang='en-US', e as vozes
    multilíngues (Thalita) às vezes leem frases inteiras em inglês por causa disso."""
    if isinstance(escaped_text, bytes):
        escaped_text = escaped_text.decode("utf-8")
    return ("<speak version='1.0' xmlns='http://www.w3.org/2001/10/synthesis' xml:lang='pt-BR'>"
            f"<voice name='{tc.voice}'>"
            f"<prosody pitch='{tc.pitch}' rate='{tc.rate}' volume='{tc.volume}'>{escaped_text}</prosody>"
            "</voice></speak>")


_edge_comm.mkssml = _ssml_ptbr

from ..voice_settings import VOICE_ALIASES

# Formato fixo do edge-tts: MP3 mono 24 kHz, 48 kbps constante.
BYTES_PER_SECOND = 48_000 / 8
TICKS_PER_SECOND = 10_000_000  # offsets de legenda vêm em unidades de 100 ns

DEFAULT_VOICE = "pt-BR-FranciscaNeural"


def resolve_voice(name: str | None) -> str:
    if not name:
        return DEFAULT_VOICE
    return VOICE_ALIASES.get(name.lower(), name)


async def list_voices(locale_prefix: str = "pt-") -> list[dict]:
    voices = await edge_tts.list_voices()
    return [v for v in voices if v["Locale"].lower().startswith(locale_prefix.lower())]


class EdgeEngine:
    extension = ".mp3"

    def __init__(
        self,
        voice: str | None = None,
        rate: str = "+0%",
        volume: str = "+0%",
        pitch: str = "+0Hz",
        concurrency: int = 3,
        retries: int = 5,
        **_ignored,
    ) -> None:
        self.voice = resolve_voice(voice)
        self.rate, self.volume, self.pitch = rate, volume, pitch
        self.concurrency = max(1, concurrency)
        self.retries = retries

    # ------------------------------------------------------------------ #
    async def _synth_chunk(self, text: str, voice: str | None = None) -> tuple[bytes, list[tuple[float, float, str]]]:
        """Sintetiza um bloco com novas tentativas em caso de falha de rede."""
        last_error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                communicate = edge_tts.Communicate(
                    text, resolve_voice(voice) if voice else self.voice, rate=self.rate, volume=self.volume, pitch=self.pitch,
                    boundary="SentenceBoundary",
                )
                audio = bytearray()
                cues: list[tuple[float, float, str]] = []
                async for msg in communicate.stream():
                    if msg["type"] == "audio":
                        audio += msg["data"]
                    elif msg["type"] in ("SentenceBoundary", "WordBoundary"):
                        start = msg["offset"] / TICKS_PER_SECOND
                        cues.append((start, start + msg["duration"] / TICKS_PER_SECOND, msg["text"]))
                if not audio:
                    raise EdgeTTSException("nenhum áudio recebido")
                return bytes(audio), cues
            except (aiohttp.ClientError, asyncio.TimeoutError, EdgeTTSException, OSError) as exc:
                last_error = exc
                wait = min(30, 2**attempt) + random.random()
                print(f"    ! falha na síntese ({exc.__class__.__name__}: {exc}); "
                      f"tentativa {attempt}/{self.retries}, aguardando {wait:.0f}s")
                await asyncio.sleep(wait)
        hint = (" O servidor não devolveu áudio para esta voz; tente outra (ex.: -v francisca)."
                if isinstance(last_error, edge_tts.exceptions.NoAudioReceived) else
                " Verifique sua conexão com a internet, ou use --engine piper (offline).")
        raise RuntimeError(f"Não foi possível sintetizar após {self.retries} tentativas.{hint}") from last_error

    async def _synth_all(self, chunks: list[str], label: str):
        sem = asyncio.Semaphore(self.concurrency)
        done = 0

        async def worker(text: str):
            nonlocal done
            async with sem:
                result = await self._synth_chunk(text)
            done += 1
            print(f"\r    {label} bloco {done}/{len(chunks)}", end="", flush=True)
            return result

        results = await asyncio.gather(*(worker(c) for c in chunks))
        print()
        return results

    # ------------------------------------------------------------------ #
    def synthesize_parts(self, parts: list[tuple[str | None, str]], out_path: Path, should_stop=None, wait_turn=None) -> list:
        """Partes com vozes diferentes (narrador e personagens) num único MP3.

        As partes são geradas em paralelo e unidas na ordem; MP3 CBR de mesmo formato
        pode ser concatenado. `should_stop` interrompe se a voz mudar no meio.
        """

        async def run():
            sem = asyncio.Semaphore(self.concurrency)

            async def one(voice, text):
                if wait_turn:
                    await asyncio.to_thread(wait_turn)
                if should_stop and should_stop():
                    return b"", []
                async with sem:
                    return await self._synth_chunk(text, voice)

            return await asyncio.gather(*(one(v, t) for v, t in parts if t.strip()))

        results = asyncio.run(run())
        if should_stop and should_stop():
            return []
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        cues, elapsed = [], 0.0
        with open(tmp, "wb") as fh:
            for audio, part_cues in results:
                fh.write(audio)
                cues += [(s + elapsed, e + elapsed, t) for s, e, t in part_cues]
                elapsed += len(audio) / BYTES_PER_SECOND
        os.replace(tmp, out_path)
        return cues

    def synthesize_part(self, chunks: list[str], out_path: Path, label: str = "") -> list[tuple[float, float, str]]:
        results = asyncio.run(self._synth_all(chunks, label))

        # Junta os blocos na ordem; MP3 CBR pode ser concatenado diretamente.
        tmp = out_path.with_suffix(out_path.suffix + ".part")
        all_cues: list[tuple[float, float, str]] = []
        elapsed = 0.0
        with open(tmp, "wb") as fh:
            for audio, cues in results:
                fh.write(audio)
                all_cues += [(s + elapsed, e + elapsed, t) for s, e, t in cues]
                elapsed += len(audio) / BYTES_PER_SECOND
        os.replace(tmp, out_path)  # só aparece o arquivo final quando estiver completo
        return all_cues
