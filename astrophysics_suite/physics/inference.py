"""Inferencia física por fila de observables -> `PhysicalInference`.

Nota de diseño: `infer_physical_parameters()` puede producir varios
parámetros en una sola llamada, cada uno potencialmente de un modelo
físico distinto (p. ej. `physical_scale_distance` para el tamaño y
`sedov_uniform_medium` para la edad, simultáneamente). `PhysicalInference`
(Fase 4) tiene un único `model_id`/`model_hypotheses` a nivel de
inferencia -- la procedencia real, por parámetro, vive en
`Quantity.method`/`Quantity.notes` de cada parámetro individual, que sí
es granular. `model_id`/`model_hypotheses` a nivel de PhysicalInference
quedan como un resumen (unión de los modelos/hipótesis realmente usados),
no como la fuente de verdad por parámetro.
"""
from __future__ import annotations

import math

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import infer_physical_parameters as _legacy_infer_physical_parameters

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.physical import PhysicalInference

ENGINE_NAME = "physics.inference"

_STATUS_TO_KIND = {
    "OBSERVADO": ValueKind.OBSERVED,
    "CALIBRADO": ValueKind.OBSERVED,
    "INFERIDO": ValueKind.MODEL_INFERENCE,
}


def infer_physical_inference(
    row: dict,
    *,
    detection_id: str,
    object_family: str = "unknown",
    distance_pc: float | None = None,
    distance_err_pc: float | None = None,
    pipeline_version: str = "",
) -> PhysicalInference:
    raw = _legacy_infer_physical_parameters(row, object_family=object_family, distance_pc=distance_pc, distance_err_pc=distance_err_pc)

    parameters: dict[str, Quantity] = {}
    models_used: list[str] = []
    hypotheses_used: set[str] = set()
    for name, p in raw["parameters"].items():
        error = p.get("error")
        if error is not None and not math.isfinite(error):
            error = None
        kind = _STATUS_TO_KIND.get(p["status"], ValueKind.HYPOTHESIS)
        model = p.get("model") or ""
        parameters[name] = Quantity(
            value=p["value"],
            error=error,
            unit=p.get("unit", ""),
            kind=kind,
            method=model or p.get("source", "unknown"),
            reference=p.get("source", ""),
            notes=tuple(p.get("assumptions") or ()),
        )
        if model:
            models_used.append(model)
            hypotheses_used.update(p.get("assumptions") or ())

    return PhysicalInference.create(
        detection_id=detection_id,
        object_family=raw["object_family"],
        model_id=", ".join(sorted(set(models_used))),
        model_hypotheses=tuple(sorted(hypotheses_used)),
        domain_valid=bool(parameters),
        parameters=parameters,
        provenance=Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=raw["engine_version"]),
    )
