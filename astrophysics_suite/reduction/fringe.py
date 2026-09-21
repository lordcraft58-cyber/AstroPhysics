"""Eliminación de patrones de franjas (fringing) -- equivalente propio
de `rmfringe`/`mkfringecor` de IRAF: escalar óptimamente un patrón de
franjas maestro (tomado con el mismo instrumento/filtro en cielo oscuro)
y sustraerlo de una imagen científica, en vez de sustraerlo con una
amplitud fija que rara vez coincide entre exposiciones.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class FringeRemovalResult:
    data: np.ndarray
    scale_factor: float


def remove_fringe(
    data: np.ndarray,
    master_fringe: np.ndarray,
    *,
    fit_region: tuple[slice, slice] | None = None,
) -> FringeRemovalResult:
    """Determina el factor de escala mediante regresión lineal de `data`
    contra `master_fringe` dentro de `fit_region` (pendiente de mínimos
    cuadrados: `scale = cov(data, fringe) / var(fringe)`, con un término
    de nivel medio libre que absorbe cualquier diferencia de fondo de
    cielo entre `data` y `master_fringe` sin afectar al ajuste de
    amplitud) y sustrae `scale * master_fringe` de la imagen completa.
    Por convención, el patrón maestro debe estar construido con su propio
    nivel cero en "sin franjas" (como ya hace cualquier fringe maestro
    real, típicamente derivado de una resta de cielo) -- de lo contrario
    la sustracción desplazaría también el fondo de cielo.
    """
    if data.shape != master_fringe.shape:
        raise ValueError(f"data y master_fringe deben tener la misma forma; {data.shape} != {master_fringe.shape}")

    region_data = data[fit_region] if fit_region is not None else data
    region_fringe = master_fringe[fit_region] if fit_region is not None else master_fringe

    fringe_mean = float(np.mean(region_fringe))
    data_mean = float(np.mean(region_data))
    fringe_centered = region_fringe - fringe_mean
    data_centered = region_data - data_mean

    denominator = float(np.sum(fringe_centered * fringe_centered))
    if denominator <= 0:
        raise ValueError("master_fringe no tiene variación en fit_region; no se puede ajustar un factor de escala")
    scale_factor = float(np.sum(data_centered * fringe_centered) / denominator)

    corrected = data.astype(np.float64) - scale_factor * master_fringe.astype(np.float64)
    return FringeRemovalResult(data=corrected, scale_factor=scale_factor)
