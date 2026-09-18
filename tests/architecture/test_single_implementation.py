"""Guarda: cada función pública crítica debe tener EXACTAMENTE una
definición de nivel de módulo. Es la petición explícita del encargo
original ("pruebas que garantizan que sólo existe una implementación
pública de cada función crítica, que launch_gui() es la activa...").

A diferencia de `tests/architecture/test_dead_code.py` (que guarda contra
la REAPARICIÓN de entidades ya eliminadas por nombre), este test guarda
de forma general contra que CUALQUIERA de estos nombres vuelva a
duplicarse en el futuro -- incluso con una implementación nueva y de
buena fe que alguien añada sin darse cuenta de que ya existe una.
"""
from __future__ import annotations

import ast
import collections
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"

# API pública considerada crítica: puntos de entrada (CLI, GUI, selftest)
# y las funciones que los hallazgos de la Fase 1-2 identificaron como
# más propensas a duplicarse en la historia del proyecto.
CRITICAL_PUBLIC_NAMES = {
    "main",
    "launch_gui",
    "selftest",
    "analyze_pair",
    "analyze_pair_core",
    "analyze_pair_with_consistency",
    "analyze_series_with_ai",
    "detect_point_sources",
    "detect_discovery_sources",
    "discovery_scan_observation",
    "resolve_object_center",
    "estimate_background",
    "measure_proper_motion",
    "stack_multiband",
    "select_optimal_profile_candidates",
    "build_parser",
}


def test_critical_names_have_exactly_one_module_level_definition():
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)

    counts: dict[str, int] = collections.Counter()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name in CRITICAL_PUBLIC_NAMES:
            counts[node.name] += 1

    missing = CRITICAL_PUBLIC_NAMES - set(counts)
    assert not missing, f"Nombres críticos que ya no existen (¿renombrados? actualiza este test): {sorted(missing)}"

    duplicated = {name: n for name, n in counts.items() if n > 1}
    assert not duplicated, f"Nombres críticos con más de una definición de nivel de módulo: {duplicated}"
