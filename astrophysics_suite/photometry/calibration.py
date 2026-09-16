"""Calibración fotométrica -- ajuste del punto cero (zeropoint) a partir
de magnitudes instrumentales medidas y magnitudes de catálogo conocidas
para las mismas estrellas, equivalente propio de la parte de calibración
de `apphot`/`photcal` de IRAF. `photometry.aperture` mide flujo/magnitud
instrumental con un punto cero arbitrario (constante); este módulo
resuelve el punto cero real contra un catálogo -- algo que el taller no
tenía hasta ahora (el punto cero era siempre una constante introducida a
mano por el usuario, nunca ajustada contra datos reales).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class ZeropointFit:
    zeropoint_mag: float
    zeropoint_uncertainty_mag: float
    n_stars_used: int
    n_stars_rejected: int
    residuals_mag: tuple[float, ...]
    """`catalog_mag - (instrumental_mag + zeropoint_mag)` de cada estrella
    finalmente usada -- para diagnóstico de calidad del ajuste."""
    rms_residual_mag: float


def fit_zeropoint(
    instrumental_mags: list[float],
    catalog_mags: list[float],
    *,
    sigma_clip: float = 3.0,
    max_iters: int = 5,
) -> ZeropointFit:
    """Cada estrella aporta un punto cero individual
    `catalog_mag - instrumental_mag` (de `catalog_mag = instrumental_mag +
    zeropoint`); el resultado es la mediana robusta de esos puntos cero
    individuales, con rechazo iterativo sigma-clip (MAD) de outliers
    (variables, mezclas, un cruce con el catálogo erróneo) -- nunca una
    media simple, que un solo outlier bastaría para desviar.
    """
    if len(instrumental_mags) != len(catalog_mags):
        raise ValueError("instrumental_mags y catalog_mags deben tener la misma longitud")
    if len(instrumental_mags) == 0:
        raise ValueError("se necesita al menos una estrella para ajustar un punto cero")

    instrumental = np.asarray(instrumental_mags, dtype=np.float64)
    catalog = np.asarray(catalog_mags, dtype=np.float64)
    individual_zeropoints = catalog - instrumental
    n_total = individual_zeropoints.size

    mask = np.ones(n_total, dtype=bool)  # True = usado en esta iteración
    for _ in range(max_iters):
        values = individual_zeropoints[mask]
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        robust_sigma = max(mad * _MAD_TO_SIGMA, 1e-9)
        new_mask = np.abs(individual_zeropoints - median) <= sigma_clip * robust_sigma
        if not np.any(new_mask):
            break
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask

    used = individual_zeropoints[mask]
    zeropoint = float(np.median(used))
    n_used = int(used.size)
    zeropoint_uncertainty = float(np.std(used, ddof=1) / np.sqrt(n_used)) if n_used > 1 else 0.0
    residuals = catalog[mask] - (instrumental[mask] + zeropoint)
    rms = float(np.sqrt(np.mean(residuals**2))) if n_used > 0 else 0.0

    return ZeropointFit(
        zeropoint_mag=zeropoint,
        zeropoint_uncertainty_mag=zeropoint_uncertainty,
        n_stars_used=n_used,
        n_stars_rejected=n_total - n_used,
        residuals_mag=tuple(float(r) for r in residuals),
        rms_residual_mag=rms,
    )
