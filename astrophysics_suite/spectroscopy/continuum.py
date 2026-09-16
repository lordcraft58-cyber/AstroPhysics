"""Ajuste de continuo -- equivalente propio de `continuum` de IRAF:
ajuste polinómico iterativo con sigma-clipping que rechaza asimétricamente
las líneas (de emisión o de absorción, según se indique) para converger
a una estimación suave del continuo subyacente, y normalización del
espectro dividiendo por ese ajuste.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class ContinuumFit:
    coefficients: np.ndarray
    continuum: np.ndarray
    """Continuo evaluado en cada píxel de entrada."""
    rms_residual: float
    n_rejected: int
    used_mask: np.ndarray
    """`True` en los píxeles que sí participaron en el ajuste final --
    `False` en los rechazados por línea (según `reject`)."""


def fit_continuum(
    wavelength: np.ndarray,
    flux: np.ndarray,
    *,
    degree: int = 3,
    sigma_clip: float = 2.5,
    max_iters: int = 10,
    reject: str = "both",
) -> ContinuumFit:
    """Ajusta un polinomio de grado `degree` a `flux(wavelength)`
    rechazando iterativamente los puntos que se desvían más de
    `sigma_clip` sigmas robustas (MAD) del ajuste actual.

    `reject`:
      - "both": rechaza por encima Y por debajo (uso general).
      - "emission": rechaza solo por encima (líneas de emisión que no
        deben tirar el continuo hacia arriba; absorciones se dejan
        influir el ajuste, apropiado para continuo estelar con líneas de
        absorción que SÍ se quiere seguir de cerca).
      - "absorption": rechaza solo por debajo (simétrico al anterior,
        para espectros dominados por líneas de emisión sobre un continuo
        débil).
    """
    if wavelength.shape != flux.shape:
        raise ValueError("wavelength y flux deben tener la misma forma")
    if reject not in ("both", "emission", "absorption"):
        raise ValueError(f"reject debe ser 'both', 'emission' o 'absorption'; recibido {reject!r}")
    if wavelength.size < degree + 1:
        raise ValueError(f"se necesitan al menos {degree + 1} puntos para un ajuste de grado {degree}")

    mask = np.ones(wavelength.size, dtype=bool)
    coefficients = np.polyfit(wavelength, flux, deg=degree)

    for _ in range(max_iters):
        coefficients = np.polyfit(wavelength[mask], flux[mask], deg=degree)
        residuals = flux - np.polyval(coefficients, wavelength)
        active_residuals = residuals[mask]
        mad = float(np.median(np.abs(active_residuals - np.median(active_residuals))))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-12)

        if reject == "both":
            new_mask = np.abs(residuals) <= sigma_clip * sigma
        elif reject == "emission":
            new_mask = residuals <= sigma_clip * sigma
        else:
            new_mask = residuals >= -sigma_clip * sigma

        if np.array_equal(new_mask, mask):
            break
        if np.count_nonzero(new_mask) < degree + 1:
            break
        mask = new_mask

    continuum = np.polyval(coefficients, wavelength)
    rms = float(math.sqrt(np.mean((flux[mask] - continuum[mask]) ** 2)))
    return ContinuumFit(
        coefficients=coefficients,
        continuum=continuum,
        rms_residual=rms,
        n_rejected=int(np.count_nonzero(~mask)),
        used_mask=mask,
    )


def normalize_by_continuum(flux: np.ndarray, continuum_fit: ContinuumFit) -> np.ndarray:
    """Divide `flux` por el continuo ajustado -- el espectro resultante
    tiene continuo ~1.0, con líneas como desviaciones relativas."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(continuum_fit.continuum != 0, flux / continuum_fit.continuum, np.nan)
