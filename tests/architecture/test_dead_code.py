"""Guarda de arquitectura: el código muerto identificado y eliminado en la
Fase 3 (docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md, seccion 1) no debe
reaparecer, y el código deliberadamente conservado-pero-sin-cablear no debe
desaparecer por accidente en una limpieza futura sin pasar antes por la
integración que le corresponde.
"""
from __future__ import annotations

import ast
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"

# Entidades de nivel de módulo confirmadas sin ninguna referencia en todo el
# archivo (verificado con AST + grep de texto plano, sin falsos positivos) y
# eliminadas en la Fase 3. Si alguna de ellas reaparece, es o bien código
# muerto reintroducido por accidente (p. ej. un revert parcial) o una nueva
# entidad que reutiliza un nombre ya retirado por confuso (ver el caso
# detect_point_sources_legacy / _detect_point_sources_legacy en la Fase 2).
REMOVED_DEAD_NAMES = {
    "_profile_selection_score",
    "launch_gui_legacy",
    "_QueueLogHandler",
    "FilterResponse",
    "build_filter_response",
    "resolve_object_center_legacy",
    "detect_point_sources_legacy",
    "estimate_field_center_from_gaia",
    "gaia_distance_pc",
    "estimate_remnant_radius_uncertainty",
    "luminosity_distance",
    "FITSQuality",
    "_survey_infer_object",
    "robust_query_simbad_field",
    "load_mappings_grid",
    "ModelParameter",
    "ModelFit",
    "compute_color_color_diagram",
    "_v44_regression_tests",
}

# Entidades igualmente sin ninguna referencia hoy, pero CONSERVADAS a
# propósito porque la Fase 1/2 las documentó como código correcto que
# todavía no está cableado a ningún punto de entrada (no como basura):
#   - check_hardware / update_check_https / download_verified_update /
#     launch_verified_installer: el flujo completo de diagnóstico y
#     actualización verificada HTTPS+SHA256 (Fase 1 sección 9); su destino
#     es services/updater.py y services/diagnostics.py en la Fase 7-9.
#   - FilamentDetectionStrategy: Protocol que documenta el contrato de
#     HessianFilamentStrategy/CannyFilamentStrategy; su destino es
#     convertirse en un contrato verificado en tiempo de ejecución en la
#     Fase 4, no borrarse.
INTENTIONALLY_UNWIRED_NAMES = {
    "check_hardware",
    "update_check_https",
    "download_verified_update",
    "launch_verified_installer",
    "FilamentDetectionStrategy",
}


def _module_level_names(tree: ast.Module) -> set[str]:
    names = set()
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            names.add(node.name)
    return names


def test_removed_dead_entities_stay_removed():
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    present = _module_level_names(tree) & REMOVED_DEAD_NAMES
    assert not present, (
        f"Entidades muertas confirmadas en la Fase 2 han reaparecido: {sorted(present)}. "
        "Si es intencional, documenta por qué en docs/audit/03-... y quítalas de "
        "REMOVED_DEAD_NAMES en este test."
    )


def test_intentionally_unwired_entities_still_exist():
    """Si estas desaparecen, deben haberlo hecho porque se integraron
    (Fase 7-9) o porque alguien las movió a un módulo services/ -- nunca
    porque un barrido de "código muerto" las borró sin mirar los docs."""
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    present = _module_level_names(tree) & INTENTIONALLY_UNWIRED_NAMES
    missing = INTENTIONALLY_UNWIRED_NAMES - present
    assert not missing, (
        f"Entidades documentadas como 'conservar, no cablear todavía' han desaparecido: "
        f"{sorted(missing)}. Si se integraron en services/, actualiza este test y el "
        "documento de auditoría en vez de simplemente borrar la entrada."
    )
