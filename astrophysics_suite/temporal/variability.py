"""Variabilidad multiépoca -> `TemporalEvidence`.
"""
from __future__ import annotations

import math

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import TemporalChangeEngine as _LegacyTemporalChangeEngine

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.temporal import TemporalEvidence

ENGINE_NAME = "temporal.variability"
ENGINE_VERSION = "1.0"


def analyze_variability(
    epochs: list[dict],
    *,
    detection_id: str,
    min_epochs: int = 3,
    sigma_threshold: float = 4.0,
    pipeline_version: str = "",
) -> TemporalEvidence:
    """`epochs`: lista de {"time"/"epoch": t, "value": y, "error"/"sigma": err}
    -- mismo contrato que `TemporalChangeEngine.analyze` heredado."""
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    raw = _LegacyTemporalChangeEngine().analyze(epochs, min_epochs=min_epochs, sigma_threshold=sigma_threshold)

    if raw["state"] != "ACTIVE":
        return TemporalEvidence.create(
            detection_id=detection_id,
            n_epochs=raw.get("n_epochs", 0),
            provenance=provenance,
            notes=(raw.get("reason", "datos insuficientes"),),
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
    )
