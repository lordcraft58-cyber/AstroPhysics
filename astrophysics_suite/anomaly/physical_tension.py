"""Tensión física interna + comparación con referencia externa ->
`AnomalyVector.physical`.
"""
from __future__ import annotations

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import PhysicalConstraintEngine as _LegacyPhysicalConstraintEngine
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import build_reference_anomaly as _legacy_build_reference_anomaly

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity

ENGINE_NAME = "anomaly.physical_tension"


def _estimates_from_quantities(parameters: dict[str, Quantity]) -> dict[str, dict]:
    return {name: {"value": q.value, "error": q.error, "unit": q.unit} for name, q in parameters.items() if q.is_available}


def physical_anomaly_quantity(
    row: dict,
    parameters: dict[str, Quantity],
    *,
    reference: dict | None = None,
    min_sigma: float = 4.0,
) -> Quantity:
    """Devuelve una única `Quantity` resumen (el mayor |z-score| entre
    tensiones internas y comparaciones de referencia significativas), con
    el desglose completo en `notes` -- nunca un booleano "es anómalo" sin
    explicación adjunta."""
    estimates = _estimates_from_quantities(parameters)
    constraints = _LegacyPhysicalConstraintEngine(min_sigma=min_sigma).evaluate(row, estimates)
    ref_anomalies = _legacy_build_reference_anomaly(row, estimates, reference=reference)

    findings: list[tuple[float, str]] = []
    for issue in constraints["issues"]:
        z = issue.get("z_score")
        if issue.get("flag") and issue.get("classification") != "measurement_issue" and z is not None:
            findings.append((abs(z), f"{issue['constraint']}: z={z:.2f}"))
    for anomaly in ref_anomalies:
        z = anomaly.get("z_score")
        if z is not None and abs(z) >= min_sigma:
            findings.append((abs(z), f"{anomaly['parameter']} vs. referencia ({anomaly['direction']}): z={z:.2f}"))

    if not findings:
        return Quantity.not_available(
            unit="sigma",
            method=ENGINE_NAME,
            reference="sin tensiones internas ni comparaciones de referencia significativas",
        )

    findings.sort(reverse=True)
    return Quantity(
        value=findings[0][0],
        error=None,
        unit="sigma",
        kind=ValueKind.OBSERVED,
        method=ENGINE_NAME,
        notes=tuple(desc for _, desc in findings),
    )
