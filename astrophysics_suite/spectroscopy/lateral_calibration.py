"""Calibración lateral/simultánea (§14, §45): un espectro de lámpara de
calibración registrado en la MISMA imagen 2D que el objeto, en una
región espacial paralela a la traza pero independiente de ella (un
canal de fibra de calibración simultánea, o una parte de la rendija
iluminada por la lámpara junto al objeto) -- para compensar flexión
mecánica u orientación entre exposiciones sin depender de una lámpara
tomada por separado en otro momento.

Es la MISMA idea geométrica que `trace.SkyWindow` (una ventana con
`offset_px`/`half_width_px` respecto al centro de la traza en cada
columna, siguiendo su curvatura), pero para una señal que NO se resta
como fondo: es la propia señal de calibración, así que aquí no hay
sustracción de cielo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.trace import ExtractedSpectrum, TraceResult, _combined_bad


@dataclass(frozen=True)
class LateralCalibrationWindow:
    """Región espacial de la lámpara de calibración lateral, relativa al
    centro de la traza del objeto en cada columna (§14: "mostrar
    regiones OBJETO/CIELO/CALIBRACIÓN")."""

    offset_px: float
    half_width_px: float


def extract_lateral_calibration_spectrum(
    data: np.ndarray,
    trace: TraceResult,
    window: LateralCalibrationWindow,
    *,
    uncertainty: np.ndarray | None = None,
    mask: np.ndarray | None = None,
    min_valid_fraction: float = 0.3,
) -> ExtractedSpectrum:
    """Suma simple en la ventana de calibración, siguiendo la traza del
    objeto desplazada `window.offset_px` (misma curvatura/inclinación:
    la lámpara lateral comparte óptica con el objeto) -- SIN sustracción
    de cielo, porque la señal de la lámpara no es fondo a restar.

    Mismo contrato de "nunca cero silencioso" que `extract_sum`: una
    columna sin evidencia usable queda `flux=NaN`, `valid=False`, nunca
    `0.0`. Si no se da `uncertainty`, `flux_uncertainty` queda `NaN` en
    vez de inventar un error que este motor no puede calcular sin una
    imagen de varianza real.
    """
    height, n_columns = data.shape
    if uncertainty is not None and uncertainty.shape != data.shape:
        raise ValueError("uncertainty debe tener la misma forma que data")
    bad = _combined_bad(data, mask)

    flux = np.full(n_columns, np.nan)
    flux_unc = np.full(n_columns, np.nan)
    valid = np.zeros(n_columns, dtype=bool)
    n_used = np.zeros(n_columns, dtype=np.int64)
    n_rejected = np.zeros(n_columns, dtype=np.int64)
    nominal_pixels = 2 * window.half_width_px + 1

    for col in range(n_columns):
        center = trace.center_px[col] + window.offset_px
        lo = max(0, int(round(center - window.half_width_px)))
        hi = min(height, int(round(center + window.half_width_px)) + 1)
        if hi <= lo:
            continue
        column_bad = bad[lo:hi, col]
        good = ~column_bad
        n_good = int(np.count_nonzero(good))
        n_rejected[col] = int(np.count_nonzero(column_bad))
        n_used[col] = n_good
        if n_good == 0 or n_good < min_valid_fraction * nominal_pixels:
            continue
        scale = nominal_pixels / n_good
        flux[col] = float(np.sum(data[lo:hi, col][good])) * scale
        if uncertainty is not None:
            flux_unc[col] = math.sqrt(float(np.sum(uncertainty[lo:hi, col][good] ** 2))) * scale
        valid[col] = True

    return ExtractedSpectrum(
        flux=flux, flux_uncertainty=flux_unc, background_per_pixel=np.full(n_columns, np.nan),
        method="lateral_calibration", valid=valid, n_pixels_used=n_used, n_pixels_rejected=n_rejected, sky=None,
    )
