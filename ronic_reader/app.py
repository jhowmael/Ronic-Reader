"""App de janela do Ronic Reader (o que roda ao dar duplo clique no "Ronic Reader.app").

Sobe o servidor local e abre uma janela nativa do macOS (WebKit, via pywebview)
com a interface. Sem o pywebview instalado, abre a mesma interface no navegador.

    python -m ronic_reader.app [arquivo.pdf]
"""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path
from urllib.parse import quote

from .player import APP_NAME
from .server import start_server

LOG_FILE = Path.home() / "Library/Logs" / f"{APP_NAME}.log"


def _setup_logging() -> None:
    """No app empacotado não há terminal: manda prints e erros para um arquivo de log."""
    if getattr(sys, "frozen", False) or sys.stdout is None or not sys.stdout.isatty():
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        log = open(LOG_FILE, "a", buffering=1, encoding="utf-8")
        log.write(f"\n=== {time.strftime('%Y-%m-%d %H:%M:%S')} iniciando ===\n")
        sys.stdout = sys.stderr = log


def _window_color() -> str:
    """Cor de fundo da janela enquanto a página carrega (segue o tema do macOS)."""
    import subprocess

    dark = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                          capture_output=True, text=True).stdout.strip() == "Dark"
    return "#1c1b1f" if dark else "#ecebef"


def _style_window(window) -> None:
    """Janela no estilo dos apps atuais do macOS: conteúdo de ponta a ponta, barra de
    título transparente com os botões de semáforo sobre a interface, e fundo com
    vibrancy (o desfoque nativo do sistema)."""
    try:
        import AppKit
        from PyObjCTools import AppHelper
    except ImportError:
        return

    def apply():
        try:
            native = window.native
            native.setStyleMask_(native.styleMask() | AppKit.NSWindowStyleMaskFullSizeContentView)
            native.setTitlebarAppearsTransparent_(True)
            native.setTitleVisibility_(AppKit.NSWindowTitleHidden)
            # barra de ferramentas vazia "unificada": semáforo mais espaçado, como no Finder
            # Barra nativa vazia no estilo "unificado": só serve para centralizar os botões
            # de janela na altura da barra de ferramentas da interface (52 px).
            if native.toolbar() is None:
                toolbar = AppKit.NSToolbar.alloc().initWithIdentifier_("RonicToolbar")
                toolbar.setShowsBaselineSeparator_(False)
                native.setToolbar_(toolbar)
                native.setToolbarStyle_(AppKit.NSWindowToolbarStyleUnified)
            if hasattr(native, "setTitlebarSeparatorStyle_"):
                native.setTitlebarSeparatorStyle_(1)  # NSTitlebarSeparatorStyleNone
            # O pywebview pinta a área da barra de título com a cor de fundo da janela
            # (opaca), o que gera a faixa escura sobre a interface. Deixa transparente.
            theme_frame = native.contentView().superview()
            for view in theme_frame.subviews():
                if "Titlebar" in view.className() and view.respondsToSelector_("setBackgroundColor:"):
                    view.setBackgroundColor_(AppKit.NSColor.clearColor())
            for view in _all_subviews(native.contentView().superview()):
                if view.isKindOfClass_(AppKit.NSClassFromString("WKWebView")):
                    view.setValue_forKey_(False, "drawsBackground")  # deixa o vibrancy aparecer
                if view.isKindOfClass_(AppKit.NSVisualEffectView):
                    view.setMaterial_(AppKit.NSVisualEffectMaterialUnderWindowBackground)
        except Exception as exc:  # estética apenas: nunca impede o app de abrir
            print("estilo da janela:", exc)

    AppHelper.callAfter(apply)


_ACCENT_OBSERVER = None  # mantém o observador vivo enquanto o app roda


def _watch_accent(window) -> None:
    """Quando você troca a cor de destaque nos Ajustes do Sistema, a interface muda junto."""
    global _ACCENT_OBSERVER
    try:
        import threading

        import AppKit
        import objc
    except ImportError:
        return

    class RonicAccentObserver(AppKit.NSObject):
        @objc.python_method
        def push(self):
            # evaluate_js espera a resposta da página: nunca chamar na thread principal
            threading.Thread(target=lambda: window.evaluate_js("window.syncAccent && syncAccent()"), daemon=True).start()

        def colorsChanged_(self, _note):
            self.push()

    _ACCENT_OBSERVER = RonicAccentObserver.alloc().init()
    center = AppKit.NSDistributedNotificationCenter.defaultCenter()
    for name in ("AppleColorPreferencesChangedNotification", "AppleAquaColorVariantChanged"):
        center.addObserver_selector_name_object_(_ACCENT_OBSERVER, "colorsChanged:", name, None)


def _all_subviews(view):
    stack = [view]
    while stack:
        v = stack.pop()
        yield v
        stack.extend(v.subviews() or [])


def _pdf_from_argv() -> str | None:
    for arg in sys.argv[1:]:
        if arg.lower().endswith((".pdf", ".epub")) and os.path.isfile(arg):
            return os.path.abspath(arg)
    return None


class JsApi:
    """Funções nativas que a página pode chamar (window.pywebview.api.*)."""

    window = None

    def zoom(self):
        """Duplo clique na barra de ferramentas: maximiza/restaura, como no macOS."""
        from PyObjCTools import AppHelper

        native = self.window.native
        AppHelper.callAfter(native.zoom_, None)

    def is_native(self):
        return True

    def set_theme(self, mode: str):
        """Tema escolhido no app (claro/escuro) ou o do sistema: vale também para o vidro nativo."""
        try:
            import AppKit
            from PyObjCTools import AppHelper

            name = {"light": AppKit.NSAppearanceNameAqua, "dark": AppKit.NSAppearanceNameDarkAqua}.get(mode)
            appearance = AppKit.NSAppearance.appearanceNamed_(name) if name else None
            AppHelper.callAfter(self.window.native.setAppearance_, appearance)
        except Exception as exc:
            print("tema:", exc)

    def accent(self):
        """Cor de destaque escolhida em Ajustes do Sistema › Aparência (ex.: "#007aff")."""
        try:
            import AppKit

            color = AppKit.NSColor.controlAccentColor().colorUsingColorSpace_(AppKit.NSColorSpace.sRGBColorSpace())
            r, g, b = (max(0, min(255, round(x * 255))) for x in
                       (color.redComponent(), color.greenComponent(), color.blueComponent()))
            return f"#{r:02x}{g:02x}{b:02x}"
        except Exception:
            return None

    def choose_image(self):
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN, directory=str(Path.home() / "Pictures"),
            file_types=("Imagens (*.jpg;*.jpeg;*.png;*.heic;*.webp;*.gif;*.tiff)",)
        )
        return result[0] if result else None

    def choose_pdf(self):
        import webview

        result = self.window.create_file_dialog(
            webview.FileDialog.OPEN, directory=str(Path.home()), file_types=("Livros (*.pdf;*.epub)",)
        )
        return result[0] if result else None


def main() -> int:
    _setup_logging()
    httpd = start_server()
    url = f"http://127.0.0.1:{httpd.server_address[1]}/"
    pdf = _pdf_from_argv()
    if pdf:
        url += f"?open={quote(pdf)}"
    print(f"Servidor em {url}")

    try:
        import webview
    except ImportError:
        import webbrowser

        webbrowser.open(url)
        print("Interface aberta no navegador. Ctrl+C para sair.")
        try:
            while True:
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0

    # Só o próprio elemento marcado arrasta a janela (botões dentro dele continuam clicáveis)
    webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True

    api = JsApi()
    api.window = webview.create_window(
        APP_NAME, url, js_api=api, width=1320, height=860, min_size=(900, 620),
        background_color=_window_color(), vibrancy=True,
    )
    # antes de aparecer (barra de título) e depois de carregar (a página só entra na janela aí)
    api.window.events.before_show += lambda: _style_window(api.window)
    api.window.events.loaded += lambda: _style_window(api.window)
    _watch_accent(api.window)
    webview.start(private_mode=False, storage_path=str(Path.home() / "Library/Application Support" / APP_NAME / "webview"))
    httpd.shutdown()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
