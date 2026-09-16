# -*- mode: python ; coding: utf-8 -*-
"""Especificación de PyInstaller para el ejecutable comercial de
AstroPhysics Suite (Fase 9). Construye en modo "onedir" (una carpeta con
el ejecutable + dependencias, no un único .exe autoextraíble) -- arranque
más rápido y mucho más fácil de depurar que "onefile" para una pila
científica de este tamaño (astropy/scipy/photutils traen datos y
extensiones binarias); ver packaging/README.md para la justificación
completa y las instrucciones de build.

Se ejecuta desde la raíz del repositorio:
    pyinstaller packaging/AstroPhysicsSuite.spec

APP_VERSION se mantiene a mano en sincronía con PIPELINE_VERSION de
qt_app/main_window.py -- deliberadamente sin importar el paquete de la
aplicación aquí (evita acoplar el análisis de PyInstaller a que todo el
árbol de imports de la app ya esté en sys.path antes de que `Analysis`
haya hecho su trabajo).
"""
import sys
from pathlib import Path

from PyInstaller.utils.hooks import collect_all

APP_NAME = "AstroPhysicsSuite"
APP_VERSION = "0.5.0"  # mantener en sincronía con qt_app/main_window.py::PIPELINE_VERSION

# `SPECPATH` lo inyecta PyInstaller con el directorio que contiene este
# .spec (packaging/); el proyecto vive un nivel por encima.
PROJECT_ROOT = Path(SPECPATH).parent  # noqa: F821 -- SPECPATH es una variable inyectada por PyInstaller
sys.path.insert(0, str(PROJECT_ROOT))

# Paquetes científicos con datos propios (tablas IERS/CDS de astropy, tipos
# de letra y estilos de matplotlib, extensiones binarias de scipy) que
# `Analysis` por sí sola no siempre descubre completas -- se piden
# explícitamente en vez de confiar en que los hooks incluidos alcancen.
datas: list = []
binaries: list = []
hiddenimports: list = []
for package in ("astropy", "photutils", "astroquery", "matplotlib", "scipy"):
    pkg_datas, pkg_binaries, pkg_hiddenimports = collect_all(package)
    datas += pkg_datas
    binaries += pkg_binaries
    hiddenimports += pkg_hiddenimports

# Los cuatro paquetes propios del proyecto: aunque `Analysis` los detecta
# por los imports reales desde `entrypoint.py`, se listan explícitos para
# que un import diferido o condicional (poco frecuente, pero presente en
# algún punto de legacy/) no deje algo fuera silenciosamente.
hiddenimports += ["astrophysics_suite", "qt_app", "services", "legacy"]

block_cipher = None

a = Analysis(
    [str(PROJECT_ROOT / "packaging" / "entrypoint.py")],
    pathex=[str(PROJECT_ROOT)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "pytest", "IPython", "notebook"],
    # `tkinter` se excluye deliberadamente: gui/ (Fase 8, Tkinter) se
    # conserva en el repositorio como referencia de diseño, pero qt_app/
    # es la interfaz final del producto (ver README.md) -- no tiene
    # sentido empaquetarla en el build comercial.
    noarchive=False,
    cipher=block_cipher,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name=APP_NAME,
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,  # aplicación de escritorio -- sin consola visible en Windows
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=None,  # ver packaging/README.md §"Icono" -- todavía no hay un .ico del proyecto
    version="packaging/version_info.txt",
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name=APP_NAME,
)
