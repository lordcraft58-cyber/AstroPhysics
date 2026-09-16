"""Máscara de píxeles defectuosos -- equivalente propio de
`ccdmask`/`fixpix` de IRAF: identificar columnas/píxeles con
sensibilidad anómala a partir de un plano maestro normalizado, e
interpolar sobre ellos en cualquier imagen calibrada.
"""
from __future__ import annotations

import numpy as np
from scipy import ndimage


def build_bad_pixel_mask(
    normalized_flat: np.ndarray,
    *,
    low_threshold: float = 0.5,
    high_threshold: float = 1.5,
) -> np.ndarray:
    """Un píxel del plano maestro normalizado (mediana 1.0, ver
    `master_frames.build_master_flat`) muy por debajo o muy por encima de
    1.0 no está midiendo la respuesta real del detector en ese punto --
    es un píxel muerto/caliente o una partícula en el sensor. Devuelve
    una máscara booleana (`True` = defectuoso)."""
    if low_threshold < 0 or high_threshold <= low_threshold:
        raise ValueError("se requiere 0 <= low_threshold < high_threshold")
    return (normalized_flat < low_threshold) | (normalized_flat > high_threshold)


def interpolate_bad_pixels(data: np.ndarray, mask: np.ndarray, *, axis: int = 1) -> np.ndarray:
    """Interpola linealmente sobre los píxeles marcados, a lo largo de
    `axis` (por defecto 1 = a lo largo de filas, como `fixpix` de IRAF,
    pensado para columnas defectuosas verticales). Un píxel defectuoso en
    el borde de su línea se rellena con el vecino válido más cercano
    (extrapolación constante) en vez de dejarlo sin corregir.
    """
    if data.shape != mask.shape:
        raise ValueError(f"data y mask deben tener la misma forma; {data.shape} != {mask.shape}")
    if axis not in (0, 1):
        raise ValueError("axis debe ser 0 o 1")

    result = data.astype(np.float64).copy()
    lines = result if axis == 1 else result.T
    mask_lines = mask if axis == 1 else mask.T

    for row, row_mask in zip(lines, mask_lines):
        if not np.any(row_mask):
            continue
        valid = ~row_mask
        if not np.any(valid):
            continue  # línea entera defectuosa: no hay nada de qué interpolar
        x = np.arange(row.size)
        row[row_mask] = np.interp(x[row_mask], x[valid], row[valid])

    return result if axis == 1 else lines.T


def flag_hot_and_cold_pixels_from_dark(master_dark_data: np.ndarray, *, n_sigma: float = 8.0) -> np.ndarray:
    """Identificación complementaria vía dark maestro: un píxel cuya
    corriente de oscuridad se desvía más de `n_sigma` sigmas robustas
    (MAD) de la mediana global es defectuoso, con independencia de lo
    que diga el plano -- algunos defectos (píxeles calientes) apenas se
    notan en un plano de cielo/domo pero dominan en un dark largo."""
    median = float(np.median(master_dark_data))
    mad = float(np.median(np.abs(master_dark_data - median)))
    robust_sigma = max(mad * 1.4826, 1e-9)
    return np.abs(master_dark_data - median) > n_sigma * robust_sigma


def smooth_bad_pixel_map(mask: np.ndarray, *, dilate_iterations: int = 0) -> np.ndarray:
    """Dilata opcionalmente la máscara (crecer 1 píxel por iteración) --
    útil cuando el defecto tiene un halo de sensibilidad degradada
    alrededor del píxel identificado, no solo el propio píxel."""
    if dilate_iterations <= 0:
        return mask
    return ndimage.binary_dilation(mask, iterations=dilate_iterations)
