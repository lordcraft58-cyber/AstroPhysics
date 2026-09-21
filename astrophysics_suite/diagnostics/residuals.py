"""`ResidualDiagnostic`: estadística real de un conjunto de residuales ya
calculado por otro motor (`WCSSolution.residuals_arcsec`,
`ZeropointFit.residuals_mag`, `WavelengthSolution.residuals`...) --
RMS, media, desviación máxima y los índices marcados como atípicos
(`diagnostics.outliers.flag_outliers`). Nunca recalcula el ajuste
original; solo resume y marca lo que ese ajuste ya produjo, para que
`reporting/`/`visualization/` puedan mostrarlo sin que cada motor tenga
que reimplementar su propio resumen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from astrophysics_suite.diagnostics.outliers import flag_outliers


@dataclass(frozen=True)
class ResidualDiagnostic:
    unit: str
    residuals: tuple[float, ...]
    rms: float
    mean: float
    max_abs: float
    outlier_indices: tuple[int, ...]


def build_residual_diagnostic(residuals: tuple[float, ...], *, unit: str, outlier_sigma: float = 3.0) -> ResidualDiagnostic:
    if not residuals:
        raise ValueError("build_residual_diagnostic necesita al menos un residuo real -- nunca se llama con un ajuste vacío")
    n = len(residuals)
    rms = math.sqrt(sum(r * r for r in residuals) / n)
    mean = sum(residuals) / n
    max_abs = max(abs(r) for r in residuals)
    outlier_indices = flag_outliers(residuals, sigma=outlier_sigma)
    return ResidualDiagnostic(unit=unit, residuals=tuple(residuals), rms=rms, mean=mean, max_abs=max_abs, outlier_indices=outlier_indices)
