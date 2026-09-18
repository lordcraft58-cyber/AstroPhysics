"""Regresión: `analyze_series_with_ai` no debe saltarse el chequeo de
consistencia científica.

Contexto (docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 7.2 y
docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md): `analyze_series_with_ai`
(el motor de series/múltiples épocas) llamaba directamente a
`analyze_pair_core`, saltándose `analyze_pair_with_consistency` -- y con
ello perdiendo `scientific_consistency`, `uncertainty_budget`,
`literature_comparison`, `anomalies`, `qc_summary`, `provenance` y
`physical_maps`, que sí reciben los análisis de un único par. Es el mismo
patrón de bug que motivó los hallazgos históricos citados por el usuario
(rutas de ejecución paralelas con contratos distintos hacia el mismo
núcleo de análisis).

La corrección (Fase 3) cambia esa llamada para que pase por `analyze_pair`
-- la API pública única declarada explícitamente en el propio código
("API pública única y explícita; no se realiza monkey-patch de símbolos
al final del módulo"). Este test fija el contrato de forma estática (vía
AST, sin necesitar imágenes FITS reales) para que no pueda reintroducirse
sin que el test lo note.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"


def _called_names(func_node: ast.FunctionDef) -> set[str]:
    names = set()
    for node in ast.walk(func_node):
        if isinstance(node, ast.Call):
            f = node.func
            if isinstance(f, ast.Name):
                names.add(f.id)
    return names


def _find_function(tree: ast.Module, name: str) -> ast.FunctionDef:
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"No se encontró la función de nivel de módulo {name!r}")


def test_analyze_series_with_ai_goes_through_public_api():
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    func = _find_function(tree, "analyze_series_with_ai")
    called = _called_names(func)

    assert "analyze_pair_core" not in called, (
        "analyze_series_with_ai llama directamente a analyze_pair_core y se "
        "salta analyze_pair_with_consistency (scientific_consistency, "
        "uncertainty_budget, literature_comparison, anomalies, qc_summary, "
        "provenance, physical_maps quedarían ausentes del payload de cada "
        "época). Debe llamar a analyze_pair()."
    )
    assert "analyze_pair" in called, (
        "analyze_series_with_ai debe invocar la API pública analyze_pair() "
        "para heredar el chequeo de consistencia científica."
    )


def test_analyze_pair_public_api_wraps_consistency_check():
    """Contrato del wrapper público en sí: debe existir exactamente una
    cadena analyze_pair -> analyze_pair_with_consistency -> analyze_pair_core,
    y ningún otro caller de nivel de módulo debe evitarla llamando a
    analyze_pair_core directamente."""
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    analyze_pair = _find_function(tree, "analyze_pair")
    assert _called_names(analyze_pair) == {"analyze_pair_with_consistency"}

    with_consistency = _find_function(tree, "analyze_pair_with_consistency")
    assert "analyze_pair_core" in _called_names(with_consistency)

    allowed_direct_callers = {"analyze_pair_with_consistency"}
    offenders = []
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name not in allowed_direct_callers:
            if "analyze_pair_core" in _called_names(node):
                offenders.append(node.name)
    assert not offenders, (
        f"Funciones que llaman a analyze_pair_core saltándose analyze_pair_with_consistency: {offenders}"
    )
