"""Corrección de cielo -- ajusta y sustrae una superficie de fondo suave de
una imagen ya calibrada. Complementa a la corrección de iluminación
(`illumination.py`, una propiedad fija del instrumento/óptica) con un
gradiente que varía de una exposición a otra -- luna, contaminación
lumínica, viñeteado residual -- y que por eso no puede capturarse en
ningún fotograma maestro. Se ajusta un polinomio 2D de bajo grado con
rechazo iterativo de fuentes (cualquier píxel muy por encima del modelo es
una fuente, no cielo) -- nunca se resta un solo valor constante, que
ignoraría cualquier gradiente real de la toma.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class SkyBackgroundFit:
    model: np.ndarray
    """Superficie de fondo ajustada, misma forma que la imagen de entrada."""
    source_mask: np.ndarray
    """`True` = píxel excluido del ajuste final por parecer una fuente, no cielo."""
    degree: int
    coefficients: np.ndarray


def _polynomial_design_matrix(shape: tuple[int, int], degree: int) -> np.ndarray:
    height, width = shape
    yy, xx = np.mgrid[0:height, 0:width]
    x = xx.astype(np.float64).ravel() / max(width - 1, 1)
    y = yy.astype(np.float64).ravel() / max(height - 1, 1)
    terms = [np.ones_like(x)]
    for total_degree in range(1, degree + 1):
        for i in range(total_degree + 1):
            j = total_degree - i
            terms.append((x**i) * (y**j))
    return np.stack(terms, axis=1)


def fit_sky_background(
    data: np.ndarray,
    *,
    degree: int = 2,
    sigma_clip: float = 3.0,
    max_iters: int = 5,
) -> SkyBackgroundFit:
    """Ajusta una superficie polinómica 2D de grado `degree` al fondo de
    cielo de `data`, rechazando iterativamente los píxeles muy por encima
    del modelo (fuentes) -- nunca por debajo, porque una depresión de
    fondo no es una fuente y descartarla sesgaría el ajuste hacia arriba.
    `degree=0` es un nivel constante (ningún gradiente); `degree=1` un
    plano; `degree=2` permite curvatura (p. ej. viñeteado residual)."""
    if degree < 0:
        raise ValueError("degree debe ser >= 0")
    design = _polynomial_design_matrix(data.shape, degree)
    values = data.astype(np.float64).ravel()
    mask = np.zeros(values.shape, dtype=bool)  # True = rechazado (fuente)

    coefficients = np.zeros(design.shape[1])
    for _ in range(max_iters):
        valid = ~mask
        coefficients, *_ = np.linalg.lstsq(design[valid], values[valid], rcond=None)
        model_values = design @ coefficients
        residual = values - model_values
        centered = residual[valid] - np.median(residual[valid])
        robust_sigma = max(float(np.median(np.abs(centered))) * _MAD_TO_SIGMA, 1e-9)
        new_mask = residual > sigma_clip * robust_sigma
        if np.array_equal(new_mask, mask):
            break
        mask = new_mask

    model = (design @ coefficients).reshape(data.shape)
    return SkyBackgroundFit(model=model, source_mask=mask.reshape(data.shape), degree=degree, coefficients=coefficients)


def subtract_sky_background(data: np.ndarray, fit: SkyBackgroundFit) -> np.ndarray:
    if data.shape != fit.model.shape:
        raise ValueError(f"data y el modelo de fondo deben tener la misma forma; {data.shape} != {fit.model.shape}")
    return data.astype(np.float64) - fit.model
