"""Recorte y máscaras de región -- utilidades genéricas de imagen
(equivalente propio de la parte de secciones/regiones de `astutil` de
IRAF), independientes de cualquier proceso concreto. `photometry.aperture`
ya tiene su propia máscara circular de apertura subpíxel
(`aperture_coverage_mask`) y `reduction.overscan` su propio recorte de
overscan -- este módulo es el recorte/máscara de propósito general que
cualquier otra parte del taller puede reutilizar sin arrastrar ese
contexto.
"""
from __future__ import annotations

import numpy as np


def crop(data: np.ndarray, region: tuple[slice, slice]) -> np.ndarray:
    """Recorta `data` a `region` (fila, columna) -- una vista, no una
    copia, igual que cualquier *slicing* de numpy; el llamador copia si
    de verdad necesita un array independiente."""
    row_slice, col_slice = region
    if data.ndim != 2:
        raise ValueError(f"crop requiere una imagen 2D; recibido ndim={data.ndim}")
    cropped = data[row_slice, col_slice]
    if cropped.size == 0:
        raise ValueError(f"la región {region} produce un recorte vacío para una imagen de forma {data.shape}")
    return cropped


def rectangular_mask(shape: tuple[int, int], region: tuple[slice, slice]) -> np.ndarray:
    """Máscara booleana de `shape` con `True` dentro de `region` (fila,
    columna) y `False` fuera."""
    mask = np.zeros(shape, dtype=bool)
    row_slice, col_slice = region
    mask[row_slice, col_slice] = True
    return mask


def circular_mask(shape: tuple[int, int], center: tuple[float, float], radius: float) -> np.ndarray:
    """Máscara booleana de `shape` con `True` dentro del círculo de
    `radius` píxeles centrado en `center` (x, y) -- sin el
    antialiasing subpíxel de `photometry.aperture.aperture_coverage_mask`,
    que existe para medir flujo con precisión; aquí basta un criterio
    binario simple de propósito general."""
    if radius <= 0:
        raise ValueError("radius debe ser positivo")
    height, width = shape
    yy, xx = np.mgrid[0:height, 0:width]
    x0, y0 = center
    return ((xx - x0) ** 2 + (yy - y0) ** 2) <= radius**2
