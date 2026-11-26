"""Ponto de entrada do app empacotado (PyInstaller)."""

import multiprocessing

from ronic_reader.app import main

if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
