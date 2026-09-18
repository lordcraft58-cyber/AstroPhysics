"""Guarda de arquitectura: ningún módulo de `astrophysics_suite/` (la
capa de ciencia objetivo) puede importar `tkinter` ni depender de ningún
detalle de presentación. Ver docs/audit/02-ARQUITECTURA-OBJETIVO-Y-
PLAN.md, seccion 3.2: "los motores científicos son importables y
ejecutables sin Tkinter... se verifica con un test de arquitectura que
falla si cualquier módulo fuera de gui/ importa tkinter".

`gui/` todavía no existe (es trabajo de la Fase 8); este test cubre lo
que sí existe hoy (`astrophysics_suite/`) para que la regla nunca se
viole desde el primer módulo, en vez de descubrirse tarde cuando ya haya
docenas de archivos que limpiar.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PACKAGE_ROOT = REPO_ROOT / "astrophysics_suite"

FORBIDDEN_MODULES = {"tkinter", "Tkinter"}


def _imported_top_level_modules(source: str) -> set[str]:
    tree = ast.parse(source)
    modules = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name.split(".")[0] for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module.split(".")[0])
    return modules


def test_astrophysics_suite_never_imports_tkinter():
    offenders = {}
    for path in PACKAGE_ROOT.rglob("*.py"):
        imported = _imported_top_level_modules(path.read_text(encoding="utf-8"))
        forbidden = imported & FORBIDDEN_MODULES
        if forbidden:
            offenders[str(path.relative_to(REPO_ROOT))] = sorted(forbidden)
    assert not offenders, f"Módulos de la capa de ciencia que importan tkinter: {offenders}"
