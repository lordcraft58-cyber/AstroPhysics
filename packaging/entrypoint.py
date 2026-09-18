"""Script de entrada para PyInstaller -- `Analysis` necesita un archivo
real, no admite `python -m qt_app` como punto de partida. No duplica
ninguna lógica: es una llamada directa a `qt_app.__main__.main`, el mismo
punto de entrada que usa un desarrollador con `python -m qt_app`."""
from __future__ import annotations

from qt_app.__main__ import main

if __name__ == "__main__":
    main()
