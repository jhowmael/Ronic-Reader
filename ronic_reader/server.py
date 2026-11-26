"""Servidor HTTP local (só 127.0.0.1) que liga a interface do app ao player.

Rotas:
    GET  /                         interface (web/index.html)
    GET  /api/state                vozes, predefinições, ajustes atuais e livros recentes
    POST /api/open?name=x.pdf      envia o PDF (corpo = bytes do arquivo)
    POST /api/open_path            {"path": "..."} abre um PDF do disco
    POST /api/open_recent          {"id": "..."}
    POST /api/settings             {"voice":..., "rate":..., ...} troca/ajusta a voz
    GET  /api/audio/<livro>/<i>    áudio do trecho i (espera ficar pronto)
    POST /api/position             {"id":..., "position": i}
    POST /api/export               {"id":...} exporta MP3 por capítulo
    GET  /api/export/<livro>       progresso da exportação
"""

from __future__ import annotations

import json
import secrets
import subprocess
import tempfile
import threading
import traceback
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from importlib import resources
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

from . import __version__
from . import narration as narr
from . import voices as catalog
from .player import EXPORT_DIR, SUPPORT_DIR, ExportJob, Library, Synthesizer, cleanup_cache, export_book, open_book
from .voice_settings import PRESET_HELP, PRESETS, describe, resolve_settings, save_config

from .voices import DEFAULT_VOICE, EDGE_VOICES, LOCAL_VOICES  # noqa: E402
MAX_UPLOAD = 500 * 1024 * 1024
# Token por sessão: só a página servida por este app conhece. Impede que sites abertos
# no navegador mandem comandos para o servidor local (requisições com cabeçalho próprio
# vindas de outra origem são bloqueadas pelo navegador).
TOKEN = secrets.token_urlsafe(24)


class App:
    """Estado compartilhado entre as requisições."""

    def __init__(self) -> None:
        self.library = Library()
        self.synth = Synthesizer()
        self.books: dict = {}
        self.exports: dict[str, ExportJob] = {}
        self.lock = threading.Lock()
        # narração por personagem: voz de narrador ou narradora conforme o trecho
        self.narration = narr.NarrationStore(SUPPORT_DIR / "narration")
        self.synth.parts_provider = self._narration_parts
        self.synth.variant_provider = self._narration_variant

    def _main_voice(self) -> tuple[str, str]:
        s = self.synth.settings
        return s.engine, s.voice or DEFAULT_VOICE[s.engine]

    def _narration_parts(self, book, idx):
        engine, main = self._main_voice()
        voice = narr.voice_for(self.narration.load(book), book, idx, engine, main)
        return [(voice, book.segments[idx].text)] if voice else None

    def _narration_variant(self, book) -> str:
        engine, main = self._main_voice()
        return narr.variant(self.narration.load(book), engine, main)

    def narration_state(self, book) -> dict:
        engine, main = self._main_voice()
        data = self.narration.load(book)
        return {"enabled": data["enabled"], "narrators": data["analysis"]["narrators"],
                "voices": narr.narrator_voices(data, engine, main),
                "pool": [v for v in catalog.catalog() if v["engine"] == engine]}

    def open_pdf(self, path: Path, name: str | None = None) -> dict:
        stored = self.library.store_pdf(path, name)
        book = open_book(stored)
        book.name = Path(name).stem if name else path.stem
        custom = self.library.data.get(book.id, {}).get("custom_name")
        if custom:
            book.title = custom
        with self.lock:
            self.books[book.id] = book
        entry = self.library.touch(book)
        return {"book": book.to_json(), "position": min(entry.get("position", 0), len(book.segments) - 1)}

    def state(self) -> dict:
        s = self.synth.settings
        voices = EDGE_VOICES + LOCAL_VOICES
        current = s.voice or DEFAULT_VOICE[s.engine]
        if not any(v["id"] == current for v in voices):
            # voz salva que não está no catálogo (ex.: escolhida antes): continua visível
            label = current.split("-")[2].replace("MultilingualNeural", "").replace("Neural", "") \
                if current.count("-") >= 2 else current
            voices = [{"id": current, "label": label, "desc": "voz em uso", "engine": s.engine,
                       "group": "Em uso"}] + voices
        return {
            "version": __version__,
            "voices": voices,
            "presets": [{"id": k, "desc": PRESET_HELP[k], **v} for k, v in PRESETS.items()],
            "settings": {**s.__dict__, "voice": s.voice or DEFAULT_VOICE[s.engine]},
            "describe": describe(s),
            "recent": self.library.recent(),
            "prefs": self.library.prefs(),
        }


APP: App | None = None


class Handler(BaseHTTPRequestHandler):
    server_version = "RonicReader"

    def log_message(self, fmt, *args):  # silencia o log padrão a cada requisição
        pass

    # ------------------------------------------------------------- helpers
    def _json(self, data, status: int = 200) -> None:
        body = json.dumps(data, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def _error(self, exc: Exception, status: int = 400) -> None:
        if status >= 500:
            traceback.print_exc()
        self._json({"error": str(exc) or exc.__class__.__name__}, status)

    def _body(self) -> bytes:
        size = int(self.headers.get("Content-Length") or 0)
        if size > MAX_UPLOAD:
            raise ValueError("Arquivo grande demais (limite de 500 MB).")
        return self.rfile.read(size) if size else b""

    def _json_body(self) -> dict:
        raw = self._body()
        return json.loads(raw) if raw else {}

    def _file(self, path: Path, ctype: str, headers: dict | None = None) -> None:
        data = path.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _authorized(self) -> bool:
        if self.headers.get("X-Ronic-Token") == TOKEN:
            return True
        self._json({"error": "não autorizado"}, 403)
        return False

    # --------------------------------------------------------------- rotas
    def do_GET(self):  # noqa: N802
        url = urlparse(self.path)
        parts = [unquote(p) for p in url.path.strip("/").split("/") if p]
        try:
            if parts and parts[0] == "api" and not self._authorized():
                return
            if not parts or parts == ["index.html"]:
                html = resources.files("ronic_reader.web").joinpath("index.html").read_text("utf-8")
                html = html.replace("__RONIC_TOKEN__", TOKEN).encode()
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(html)))
                self.end_headers()
                self.wfile.write(html)
            elif parts == ["api", "state"]:
                self._json(APP.state())
            elif len(parts) == 4 and parts[:2] == ["api", "audio"]:
                book = APP.books.get(parts[2])
                if not book:
                    return self._json({"error": "Livro não está aberto."}, 404)
                idx = int(parts[3])
                if not 0 <= idx < len(book.segments):
                    return self._json({"error": "Trecho inexistente."}, 404)
                part = parse_qs(url.query).get("part", ["full"])[0]
                if part not in ("full", "head", "tail"):
                    part = "full"
                try:
                    path = APP.synth.request(book, idx, part).result(timeout=600)
                except Exception as exc:
                    return self._error(exc, 409 if exc.__class__.__name__ in ("Cancelled", "CancelledError") else 502)
                # "full" no cabeçalho avisa a página que não precisa pedir o resto
                served = "full" if part != "full" and "-h" not in path.stem and "-t" not in path.stem else part
                self._file(path, "audio/mpeg" if path.suffix == ".mp3" else "audio/wav", {"X-Ronic-Part": served})
            elif len(parts) == 3 and parts[:2] == ["api", "cover"]:
                cover = APP.library.cover(parts[2])
                if not cover:
                    return self._json({"error": "sem capa"}, 404)
                self._file(cover, "image/jpeg")
            elif len(parts) == 3 and parts[:2] == ["api", "narration"]:
                book = APP.books.get(parts[2])
                if not book:
                    return self._json({"error": "Livro não está aberto."}, 404)
                self._json(APP.narration_state(book))
            elif len(parts) == 3 and parts[:2] == ["api", "export"]:
                job = APP.exports.get(parts[2])
                self._json(job.to_json() if job else {"status": "none"})
            else:
                self._json({"error": "rota não encontrada"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception as exc:
            self._error(exc, 500)

    def do_POST(self):  # noqa: N802
        url = urlparse(self.path)
        if not self._authorized():
            return
        try:
            if url.path == "/api/open":
                name = parse_qs(url.query).get("name", ["livro.pdf"])[0]
                data = self._body()
                if data.startswith(b"%PDF"):
                    suffix = ".pdf"
                elif data.startswith(b"PK") and b"application/epub+zip" in data[:200]:
                    suffix = ".epub"
                else:
                    raise ValueError("Esse arquivo não é PDF nem EPUB.")
                with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                    tmp.write(data)
                try:
                    self._json(APP.open_pdf(Path(tmp.name), name))
                finally:
                    Path(tmp.name).unlink(missing_ok=True)

            elif url.path == "/api/open_path":
                path = Path(self._json_body()["path"]).expanduser()
                if not path.is_file():
                    raise ValueError(f"Arquivo não encontrado: {path}")
                self._json(APP.open_pdf(path))

            elif url.path == "/api/open_recent":
                book_id = self._json_body()["id"]
                entry = APP.library.data.get(book_id)
                if not entry:
                    raise ValueError("Livro não encontrado na biblioteca.")
                self._json(APP.open_pdf(Path(entry["path"]), entry["name"] + ".pdf"))

            elif url.path == "/api/remove_recent":
                APP.library.remove(self._json_body()["id"])
                self._json({"ok": True})

            elif url.path == "/api/settings":
                body = self._json_body()
                cli = {k: body.get(k) for k in ("engine", "voice", "rate", "volume", "pitch", "expressiveness")}
                settings = resolve_settings(cli, body.get("preset"), config={})
                APP.synth.set_settings(settings)
                save_config(settings)
                self._json(APP.state())

            elif url.path == "/api/narration":
                body = self._json_body()
                book = APP.books.get(body.get("id"))
                if not book:
                    raise ValueError("Abra o livro primeiro.")
                engine, _ = APP._main_voice()
                APP.narration.update(book, body, engine)
                APP.synth.invalidate()
                self._json(APP.narration_state(book))

            elif url.path == "/api/prepare_voice":
                body = self._json_body()
                book = APP.books.get(body.get("id"))
                if book and 0 <= int(body.get("index", -1)) < len(book.segments):
                    cli = {k: body.get(k) for k in ("engine", "voice", "rate", "volume", "pitch", "expressiveness")}
                    APP.synth.speculate(book, int(body["index"]), resolve_settings(cli, None, config={}))
                self._json({"ok": True})

            elif url.path == "/api/position":
                body = self._json_body()
                APP.library.set_position(body["id"], body["position"], body.get("page"))
                self._json({"ok": True})

            elif url.path == "/api/library/rename":
                body = self._json_body()
                entry = APP.library.rename(body["id"], body.get("name", ""))
                book = APP.books.get(body["id"])
                if book:
                    book.title = entry.get("custom_name") or entry.get("name") or book.title
                self._json(APP.state())

            elif url.path == "/api/library/cover":
                body = self._json_body()
                image = Path(body["path"]).expanduser() if body.get("path") else None
                if image and not image.is_file():
                    raise ValueError(f"Imagem não encontrada: {image}")
                APP.library.set_cover(body["id"], page=body.get("page"), image=image, reset=bool(body.get("reset")))
                self._json(APP.state())

            elif url.path == "/api/library/cover_upload":
                book_id = parse_qs(url.query).get("id", [""])[0]
                APP.library.set_cover(book_id, data=self._body())
                self._json(APP.state())

            elif url.path == "/api/prefs":
                self._json(APP.library.set_prefs(self._json_body()))

            elif url.path == "/api/export":
                book = APP.books.get(self._json_body()["id"])
                if not book:
                    raise ValueError("Abra o livro antes de exportar.")
                old = APP.exports.get(book.id)
                if old and old.status == "running":
                    return self._json(old.to_json())
                job = ExportJob(book.id, len(book.segments))
                APP.exports[book.id] = job
                threading.Thread(target=export_book, args=(book, APP.synth, job), daemon=True).start()
                self._json(job.to_json())

            elif url.path == "/api/export_cancel":
                job = APP.exports.get(self._json_body()["id"])
                if job:
                    job.cancel.set()
                self._json({"ok": True})

            elif url.path == "/api/reveal":
                folder = Path(self._json_body()["folder"]).resolve()
                if EXPORT_DIR.resolve() not in (folder, *folder.parents):
                    raise ValueError("Pasta fora da área de exportação.")
                subprocess.run(["open", str(folder)], check=False)
                self._json({"ok": True})
            else:
                self._json({"error": "rota não encontrada"}, 404)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except (ValueError, KeyError) as exc:
            self._error(exc, 400)
        except Exception as exc:
            self._error(exc, 500)


def start_server(port: int = 0) -> ThreadingHTTPServer:
    """Sobe o servidor numa porta livre de 127.0.0.1, em segundo plano."""
    global APP
    APP = App()
    threading.Thread(target=cleanup_cache, daemon=True).start()
    APP.synth.warm_up()
    httpd = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    httpd.daemon_threads = True
    threading.Thread(target=httpd.serve_forever, daemon=True).start()
    return httpd
