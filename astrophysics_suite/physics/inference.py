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

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.physical import PhysicalInference

ENGINE_NAME = "physics.inference"
PHYSICAL_ENGINE_VERSION = "1.0"

_STATUS_TO_KIND = {
    "OBSERVADO": ValueKind.OBSERVED,
    "CALIBRADO": ValueKind.OBSERVED,
    "INFERIDO": ValueKind.MODEL_INFERENCE,
}


def _get_float(d: dict, *keys: str) -> float:
    for k in keys:
        if k in d:
            try:
                v = float(d.get(k))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                return v
    return float("nan")


def _estimate_error(d: dict, *keys: str) -> float:
    for k in keys:
        if k in d:
            try:
                v = abs(float(d.get(k)))
            except (TypeError, ValueError):
                continue
            if math.isfinite(v):
                return v
    return float("nan")


def _infer_physical_parameters(row: dict, *, object_family: str = "unknown", distance_pc: float | None = None, distance_err_pc: float | None = None) -> dict:
    """Extrae parámetros físicamente permitidos de una observación --
    migrado 1:1 del `infer_physical_parameters` heredado (cierre
    sistemático del motor 11/16, informe 99). Devuelve explícitamente
    OBSERVADO/CALIBRADO/INFERIDO y evita inferencias cuando faltan
    observables esenciales -- ninguna fórmula ni criterio cambiado
    respecto a la versión heredada.

    `registry` (el `PhysicalModelRegistry` heredado) no se migra: en la
    implementación original se construye pero nunca se consulta dentro
    de esta función (verificado leyendo su cuerpo completo), y ningún
    llamador real de la suite le pasaba un registro propio -- parámetro
    vestigial, no una pieza real de la lógica."""
    r = dict(row or {})
    estimates: list[dict] = []
    family = str(object_family or "unknown").lower()
    dpc = float(distance_pc) if distance_pc is not None and math.isfinite(float(distance_pc)) else float("nan")
    depc = float(distance_err_pc) if distance_err_pc is not None and math.isfinite(float(distance_err_pc)) else float("nan")
    if not math.isfinite(dpc):
        dpc = _get_float(r, "distance_pc")
    if not math.isfinite(depc):
        depc = _get_float(r, "distance_err_pc")

    def _estimate(name, value, error, unit, status, source, model=None, assumptions=None):
        # `json_sanitize` heredado convierte NaN/inf a None al serializar
        # un `ParameterEstimate` -- se replica aquí para que el dict crudo
        # sea idéntico al heredado, no solo el `Quantity` final (que ya
        # normaliza NaN->None por su cuenta en `infer_physical_inference`).
        value = float(value) if math.isfinite(value) else None
        error = float(error) if error is not None and math.isfinite(error) else None
        estimates.append({
            "name": name, "value": value, "error": error, "unit": unit, "status": status,
            "source": source, "model": model, "assumptions": list(assumptions or []),
        })

    ratio = _get_float(r, "ratio", "oiii_ha_ratio")
    ratio_err = _estimate_error(r, "ratio_err", "oiii_ha_ratio_err")
    if math.isfinite(ratio) and ratio > 0:
        lr = math.log10(ratio)
        lre = (ratio_err / (ratio * math.log(10))) if math.isfinite(ratio_err) else float("nan")
        _estimate("log10_oiii_over_ha", lr, lre, "dex", "OBSERVADO", "pipeline_ratio")

    off = _get_float(r, "offset_arcsec")
    offe = _estimate_error(r, "offset_err_arcsec")
    if math.isfinite(off):
        _estimate("offset_arcsec", off, offe, "arcsec", "OBSERVADO", "geometry")

    # Physical scale from small-angle approximation.
    if math.isfinite(off) and math.isfinite(dpc) and dpc > 0:
        size_pc = off / 206265.0 * dpc
        err = float("nan")
        if math.isfinite(offe) and off > 0 and math.isfinite(depc) and depc > 0:
            err = abs(size_pc) * math.sqrt((offe / off) ** 2 + (depc / dpc) ** 2)
        _estimate("offset_pc", size_pc, err, "pc", "INFERIDO", "geometry", "physical_scale_distance", ["small_angle"])

    v = _get_float(r, "velocity_kms", "v_kms")
    ve = _estimate_error(r, "velocity_err_kms", "v_err_kms")
    if math.isfinite(v) and v > 0:
        # Fully ionized monoatomic strong-shock temperature, explicitly model-dependent.
        kB = 1.380649e-23
        mp = 1.67262192369e-27
        mu = 0.61
        gamma = 5.0 / 3.0
        # T = 2(gamma-1)/(gamma+1)^2 * mu mp v^2 / kB; for gamma=5/3 => 3/16
        coeff = (2 * (gamma - 1) / (gamma + 1) ** 2) * mu * mp / kB
        t = coeff * (v * 1e3) ** 2
        te = abs(t * 2 * ve / max(v, 1e-12)) if math.isfinite(ve) else float("nan")
        _estimate("postshock_temperature_K", t, te, "K", "INFERIDO", "rankine_hugoniot", "strong_shock_temperature", ["gamma=5/3", "mu=0.61"])

        rad = _get_float(r, "radius_pc")
        rade = _estimate_error(r, "radius_err_pc")
        if math.isfinite(rad) and rad > 0:
            # Sedov-style age coefficient 2/5; this is only a dynamical age proxy under the stated model.
            age_yr = (2.0 / 5.0) * rad * 3.0856775814913673e13 / (v * 1e3) / (365.25 * 86400.0)
            ae = float("nan")
            if math.isfinite(rade) and math.isfinite(ve):
                ae = abs(age_yr) * math.sqrt((rade / rad) ** 2 + (ve / v) ** 2)
            _estimate("age_yr", age_yr, ae, "yr", "INFERIDO", "Sedov-Taylor expansion", "sedov_uniform_medium", ["spherical", "adiabatic", "uniform_medium"])

    # Optional calibrated fluxes.
    for name, valkeys, errkeys, unit in [
        ("flux_ha", ("flux_ha_calibrated", "flux_ha"), ("flux_ha_err", "flux_ha_calibrated_err"), "flux"),
        ("flux_oiii", ("flux_oiii_calibrated", "flux_oiii"), ("flux_oiii_err", "flux_oiii_calibrated_err"), "flux"),
    ]:
        val = _get_float(r, *valkeys)
        err = _estimate_error(r, *errkeys)
        if math.isfinite(val):
            status = "CALIBRADO" if any(k in r for k in valkeys if "calibrated" in k) else "OBSERVADO"
            _estimate(name, val, err, unit, status, "pipeline")

    return {
        "engine_version": PHYSICAL_ENGINE_VERSION,
        "object_family": family,
        "parameters": {e["name"]: e for e in estimates},
        "available": [e["name"] for e in estimates],
        "notes": ["Los parámetros INFERIDO dependen explícitamente del modelo indicado."],
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
    raw = _infer_physical_parameters(row, object_family=object_family, distance_pc=distance_pc, distance_err_pc=distance_err_pc)

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
