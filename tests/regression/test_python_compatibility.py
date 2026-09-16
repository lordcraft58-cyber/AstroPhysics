"""Regresión del hallazgo P0 de la Fase 1: el archivo debe parsear en la
versión mínima de Python objetivo, no solo en la versión del entorno de
desarrollo.

Contexto (docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 1): una f-string
con comillas escapadas dentro de la expresión (PEP 701, solo válido desde
Python 3.12) impedía que el archivo completo se pudiera siquiera importar
en Python 3.10/3.11 -- versiones todavía muy usadas para builds de
PyInstaller. `ast.parse(..., feature_version=...)` NO detecta esta clase de
error (verificado empíricamente: el parámetro no cubre la gramática de
f-strings de PEP 701), así que la única guarda fiable es invocar un
intérprete real de la versión mínima soportada.
"""
from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"

# Versión mínima de Python que el producto comercial debe soportar (ver
# docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md, seccion 4.3). Se revisa
# explícitamente aquí en vez de asumirse implícitamente.
MIN_SUPPORTED_PYTHON = "3.11"


def _interpreter_for(version: str) -> str | None:
    return shutil.which(f"python{version}")


@pytest.mark.parametrize("version", ["3.10", "3.11"])
def test_legacy_module_parses_on_minimum_supported_python(version):
    interpreter = _interpreter_for(version)
    if interpreter is None:
        pytest.skip(f"python{version} no está instalado en este entorno")
    result = subprocess.run(
        [interpreter, "-c", "import ast, sys; ast.parse(open(sys.argv[1], encoding='utf-8').read())", str(LEGACY_PATH)],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, (
        f"legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py no parsea en Python {version}:\n{result.stderr}"
    )


def test_legacy_module_parses_on_current_interpreter():
    import ast

    source = LEGACY_PATH.read_text(encoding="utf-8")
    ast.parse(source)  # no debe lanzar SyntaxError


def test_legacy_module_has_no_backslash_inside_fstring_expression():
    """Guarda específica y barata: ninguna f-string debe tener `\\` dentro de
    una expresión `{...}` -- es la construcción concreta que rompía Python
    <3.12 (PEP 701). No sustituye al test de arriba (que es la verificación
    real), pero falla más rápido y sin necesitar un intérprete adicional.
    """
    import ast

    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    offenders = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.JoinedStr):
            continue
        for value in node.values:
            if isinstance(value, ast.FormattedValue):
                expr_src = ast.get_source_segment(source, value.value)
                if expr_src and "\\" in expr_src:
                    offenders.append((node.lineno, expr_src))
    assert not offenders, f"Backslash dentro de expresión f-string (rompe Python <3.12): {offenders}"
