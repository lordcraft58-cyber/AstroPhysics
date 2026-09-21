"""Variabilidad multiépoca -> `TemporalEvidence`.
"""
from __future__ import annotations

import math

import numpy as np

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.temporal import TemporalEpoch, TemporalEvidence

ENGINE_NAME = "temporal.variability"
ENGINE_VERSION = "1.0"


def _parse_epochs(epochs: list[dict]) -> tuple[TemporalEpoch, ...]:
    """Mismo filtro que `_analyze_temporal_change` aplica antes de
    ajustar -- para que los puntos que `reporting/` dibuje sean
    EXACTAMENTE los que el motor usó de verdad, nunca puntos malformados
    que el motor descartó en silencio."""
    parsed: list[TemporalEpoch] = []
    for e in epochs:
        if not isinstance(e, dict):
            continue
        try:
            t = float(e.get("time", e.get("epoch", float("nan"))))
            y = float(e.get("value", float("nan")))
        except (TypeError, ValueError):
            continue
        try:
            sy = abs(float(e.get("error", e.get("sigma", float("nan")))))
        except (TypeError, ValueError):
            sy = float("nan")
        if math.isfinite(t) and math.isfinite(y) and math.isfinite(sy) and sy > 0:
            parsed.append(TemporalEpoch(time=t, value=y, error=sy))
    return tuple(parsed)


def _weighted_linear_fit(x: np.ndarray, y: np.ndarray, sigma: np.ndarray) -> dict:
    """Ajuste lineal ponderado por mínimos cuadrados, con covarianza
    explícita -- migrado 1:1 del `_weighted_linear_fit` heredado (motor
    de variabilidad, cierre sistemático del motor 9/16, informe 97)."""
    x = np.asarray(x, dtype=float).ravel()
    y = np.asarray(y, dtype=float).ravel()
    sigma = np.maximum(np.abs(np.asarray(sigma, dtype=float).ravel()), 1e-15)
    mask = np.isfinite(x) & np.isfinite(y) & np.isfinite(sigma) & (sigma > 0)
    x, y, sigma = x[mask], y[mask], sigma[mask]
    if x.size < 2:
        raise ValueError("Se requieren al menos dos observaciones válidas")
    design = np.column_stack([np.ones(x.size), x])
    weights = 1.0 / (sigma * sigma)
    a = design.T @ (design * weights[:, None])
    b = design.T @ (weights * y)
    cov = np.linalg.pinv(a)
    beta = cov @ b
    resid = (y - design @ beta) / sigma
    chi2 = float(np.sum(resid * resid))
    dof = max(1, x.size - 2)
    return {
        "intercept": float(beta[0]),
        "slope": float(beta[1]),
        "intercept_err": float(math.sqrt(max(cov[0, 0], 0))),
        "slope_err": float(math.sqrt(max(cov[1, 1], 0))),
        "chi2": chi2,
        "reduced_chi2": float(chi2 / dof),
        "n": int(x.size),
    }


def _analyze_temporal_change(epochs: list[dict], *, min_epochs: int, sigma_threshold: float) -> dict:
    """Busca variabilidad/deriva en medidas multiépoca con errores
    explícitos -- migrado 1:1 del `TemporalChangeEngine.analyze` heredado
    (cierre sistemático del motor 9/16, informe 97): chi² constante vs.
    ajuste lineal ponderado, misma decisión de `variable_candidate`."""
    points: list[tuple[float, float, float]] = []
    for e in epochs:
        if not isinstance(e, dict):
            continue
        try:
            t = float(e.get("time", e.get("epoch", float("nan"))))
            y = float(e.get("value", float("nan")))
        except (TypeError, ValueError):
            continue
        try:
            sy = abs(float(e.get("error", e.get("sigma", float("nan")))))
        except (TypeError, ValueError):
            sy = float("nan")
        if math.isfinite(t) and math.isfinite(y) and math.isfinite(sy) and sy > 0:
            points.append((t, y, sy))

    if len(points) < min_epochs:
        return {"engine_version": "1.0", "state": "NO DATA", "reason": f"se requieren >= {min_epochs} épocas", "n_epochs": len(points)}

    arr = np.asarray(points, dtype=float)
    t, y, sy = arr[:, 0], arr[:, 1], arr[:, 2]
    weights = 1.0 / (sy * sy)
    weighted_mean = float(np.sum(weights * y) / np.sum(weights))
    constant_chi2 = float(np.sum(((y - weighted_mean) / sy) ** 2))
    dof = max(1, len(y) - 1)

    fit = _weighted_linear_fit(t - t.mean(), y, sy)
    slope_sigma = fit["slope"] / fit["slope_err"] if fit["slope_err"] > 0 else float("nan")
    return {
        "engine_version": "1.0",
        "state": "ACTIVE",
        "n_epochs": int(len(y)),
        "weighted_mean": weighted_mean,
        "constant_chi2": constant_chi2,
        "constant_reduced_chi2": constant_chi2 / dof,
        "linear_fit": fit,
        "slope_sigma": float(slope_sigma) if math.isfinite(slope_sigma) else None,
        "variable_candidate": bool((math.isfinite(slope_sigma) and abs(slope_sigma) >= sigma_threshold) or constant_chi2 / dof > 2.5),
        "threshold_sigma": float(sigma_threshold),
        "notes": [
            "La variabilidad requiere repetición temporal y errores por época.",
            "No se interpreta como variabilidad física sin descartar cambios instrumentales.",
        ],
    }


def analyze_variability(
    epochs: list[dict],
    *,
    detection_id: str,
    min_epochs: int = 3,
    sigma_threshold: float = 4.0,
    pipeline_version: str = "",
) -> TemporalEvidence:
    """`epochs`: lista de {"time"/"epoch": t, "value": y, "error"/"sigma": err}."""
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    raw = _analyze_temporal_change(epochs, min_epochs=min_epochs, sigma_threshold=sigma_threshold)
    real_epochs = _parse_epochs(epochs)

    if raw["state"] != "ACTIVE":
        return TemporalEvidence.create(
            detection_id=detection_id,
            n_epochs=raw.get("n_epochs", 0),
            provenance=provenance,
            notes=(raw.get("reason", "datos insuficientes"),),
            epochs=real_epochs,
        )

    fit = raw["linear_fit"]
    brightness_change = None
    if math.isfinite(fit.get("slope", float("nan"))) and math.isfinite(fit.get("slope_err", float("nan"))):
        brightness_change = Quantity(
            value=fit["slope"], error=fit["slope_err"], unit="value/epoch", kind=ValueKind.OBSERVED, method="weighted_linear_fit"
        )

    return TemporalEvidence.create(
        detection_id=detection_id,
        n_epochs=raw["n_epochs"],
        provenance=provenance,
        variable_candidate=raw["variable_candidate"],
        brightness_change=brightness_change,
        notes=tuple(raw.get("notes", ())),
        epochs=real_epochs,
    )
