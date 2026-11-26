# -*- mode: python ; coding: utf-8 -*-
# Receita do PyInstaller para gerar "Ronic Reader.app".
# Use:  ./packaging/build_macos.sh   (ou: pyinstaller packaging/RonicReader.spec)

from PyInstaller.utils.hooks import collect_all, collect_data_files

from ronic_reader import __version__

datas = [("../ronic_reader/web/index.html", "ronic_reader/web")]
binaries = []
hiddenimports = ["ronic_reader.web", "ronic_reader.tts.edge", "ronic_reader.tts.piper", "ronic_reader.tts.kokoro",
                 "ronic_reader.epub", "lameenc"]

# Pacotes com dados/binários que o PyInstaller não acha sozinho
for pkg in ("piper", "onnxruntime", "pypdfium2", "pypdfium2_raw", "edge_tts", "certifi",
            "kokoro_onnx", "espeakng_loader", "phonemizer", "pillow_heif"):
    d, b, h = collect_all(pkg)
    datas += d
    binaries += b
    hiddenimports += h
datas += collect_data_files("pdfminer")  # tabelas de fontes (CMaps) do pdfplumber

a = Analysis(
    ["launcher.py"],
    pathex=[".."],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    excludes=["tkinter", "matplotlib", "PyQt5", "PyQt6", "PySide6", "pytest", "fpdf", "torch", "tensorflow", "jax", "flax",
              "mlx", "mlx_lm", "transformers"],
    noarchive=False,
)
pyz = PYZ(a.pure)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Ronic Reader",
    console=False,
    argv_emulation=True,  # recebe o PDF quando aberto pelo Finder ("Abrir com")
    target_arch=None,
    codesign_identity=None,
)
coll = COLLECT(exe, a.binaries, a.datas, name="Ronic Reader")

app = BUNDLE(
    coll,
    name="Ronic Reader.app",
    icon="RonicReader.icns",
    bundle_identifier="local.ronic.reader",
    version=__version__,
    info_plist={
        "CFBundleDisplayName": "Ronic Reader",
        "CFBundleShortVersionString": __version__,
        "NSHighResolutionCapable": True,
        "LSApplicationCategoryType": "public.app-category.books",
        "LSMinimumSystemVersion": "12.0",
        # A interface é servida por um servidor local (http://127.0.0.1); sem isto o
        # WebKit do app empacotado bloqueia a página e a janela fica vazia.
        "NSAppTransportSecurity": {"NSAllowsLocalNetworking": True},
        # Aparece em "Abrir com" para PDFs e aceita PDF arrastado sobre o ícone
        "CFBundleDocumentTypes": [{
            "CFBundleTypeName": "PDF",
            "CFBundleTypeRole": "Viewer",
            "LSHandlerRank": "Alternate",
            "LSItemContentTypes": ["com.adobe.pdf"],
        }],
    },
)
