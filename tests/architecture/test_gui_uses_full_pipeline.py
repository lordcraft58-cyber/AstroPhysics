"""El encargo original pide explícitamente: "Agregue también pruebas que
garantizan... que la GUI utiliza el pipeline científico completo y no
una variante incompleta."

Hoy esto NO es cierto: la Fase 2 (docs/audit/03-MAPEO-DEPENDENCIAS-Y-
CONTRATOS.md, seccion 2) cuantificó que 78 entidades vivas son
alcanzables desde `main()` (CLI) y ninguna de ellas desde `launch_gui()`
-- entre ellas, la totalidad del motor físico, el motor de anomalías y
el motor de evidencia (`PhysicalConstraintEngine`, `SpatialTrendAnomaly
Engine`, `TemporalChangeEngine`, `DiscoveryEvidenceEngine`,
`infer_physical_parameters`, `discovery_v46`).

Este test fija esa carencia como un `xfail` ESTRICTO (no silencioso):
mientras la GUI no llegue a estos motores, el test se reporta como
"fallo esperado" y el pendiente queda visible en cada corrida de la
suite. El día que la Fase 7/8 conecte la GUI al pipeline completo, este
test empezará a "pasar inesperadamente" (XPASS) y `strict=True` lo
convertirá en un fallo duro de CI -- forzando a que alguien quite el
marcador `xfail` de forma consciente, momento en el que este test pasa a
ser una guarda real y permanente contra que la GUI vuelva a quedarse
corta. No se elimina el test al cerrar la Fase 7: se le quita el
`xfail`.
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
LEGACY_PATH = REPO_ROOT / "legacy" / "AstroPhysicsSuite_v57_3_COMMERCIAL.py"

# Motores que el encargo original describe como el núcleo científico del
# producto -- el mínimo que una GUI comercial debe poder alcanzar para
# no ser "una variante incompleta" del pipeline.
CORE_ENGINES_GUI_MUST_REACH = {
    "infer_physical_parameters",  # Physical Engine
    "PhysicalConstraintEngine",  # Anomaly Engine (restricciones físicas)
    "SpatialTrendAnomalyEngine",  # Anomaly Engine (anomalías espaciales, FDR)
    "TemporalChangeEngine",  # Temporal Engine
    "DiscoveryEvidenceEngine",  # Evidence Engine -- el núcleo conceptual del producto
}


def _build_reference_graph(tree: ast.Module) -> dict[str, set[str]]:
    top_level = {
        node.name: node
        for node in tree.body
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef))
    }
    refs: dict[str, set[str]] = {}
    for name, node in top_level.items():
        names_used = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
        refs[name] = (names_used & set(top_level)) - {name}
    return refs


def _reachable_from(seed: str, refs: dict[str, set[str]]) -> set[str]:
    seen = {seed}
    stack = [seed]
    while stack:
        current = stack.pop()
        for target in refs.get(current, ()):
            if target not in seen:
                seen.add(target)
                stack.append(target)
    return seen


@pytest.mark.xfail(
    reason="La GUI activa (launch_gui) todavía no alcanza el motor físico/de anomalías/de evidencia -- ver docs/audit/03-..., seccion 2. Pendiente de la Fase 7/8.",
    strict=True,
)
def test_launch_gui_reaches_the_core_discovery_engines():
    source = LEGACY_PATH.read_text(encoding="utf-8")
    tree = ast.parse(source)
    refs = _build_reference_graph(tree)

    reachable_from_gui = _reachable_from("launch_gui", refs)
    missing = CORE_ENGINES_GUI_MUST_REACH - reachable_from_gui
    assert not missing, f"launch_gui() no alcanza estos motores núcleo: {sorted(missing)}"
