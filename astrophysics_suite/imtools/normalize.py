"""Normalización de imagen -- utilidad genérica de inspección/preparación
(equivalente propio de la parte de normalización de `astutil` de IRAF),
independiente de la normalización a mediana 1.0 que ya hace
`reduction.master_frames.build_master_flat` para un fotograma de
calibración concreto (esa es específica del significado físico de un
flat; esta es de propósito general, para visualización o preprocesado).
"""
from __future__ import annotations

import numpy as np

_MAD_TO_SIGMA = 1.4826


def normalize_minmax(data: np.ndarray) -> np.ndarray:
    """Reescala linealmente a [0, 1] usando el mínimo/máximo reales de
    los píxeles finitos -- sensible a un solo valor extremo, por diseño
    (igual que cualquier normalización min-max clásica; usa
    `normalize_percentile` si eso es un problema)."""
    values = data.astype(np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no hay píxeles finitos para normalizar")
    minimum, maximum = float(np.min(finite)), float(np.max(finite))
    span = maximum - minimum
    if span <= 0:
        raise ValueError(f"la imagen no tiene rango dinámico (min == max == {minimum})")
    return (values - minimum) / span


def normalize_percentile(data: np.ndarray, *, low: float = 1.0, high: float = 99.0) -> np.ndarray:
    """Reescala usando los percentiles `low`/`high` como extremos en vez
    del mínimo/máximo -- mucho menos sensible a un solo píxel extremo
    (saturación, rayo cósmico) que `normalize_minmax`. Los valores fuera
    de ese rango no se recortan: el resultado puede salir de [0, 1]."""
    if not (0 <= low < high <= 100):
        raise ValueError("se requiere 0 <= low < high <= 100")
    values = data.astype(np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no hay píxeles finitos para normalizar")
    p_low, p_high = np.percentile(finite, [low, high])
    span = float(p_high - p_low)
    if span <= 0:
        raise ValueError(f"el rango entre los percentiles {low} y {high} no es positivo")
    return (values - p_low) / span


def normalize_sigma_clip(data: np.ndarray, *, center: str = "median", n_sigma: float = 3.0, clip: bool = True) -> np.ndarray:
    """Centra y escala por una medida robusta de dispersión (MAD ->
    sigma), no por la media/desviación clásicas -- el resultado es el
    número de sigmas robustas que cada píxel se desvía de `center`,
    pensado para resaltar outliers (fuentes, defectos) frente al fondo,
    no para llevar la imagen a un rango [0, 1]. Con `clip=True` (por
    defecto), el resultado se recorta a `[-n_sigma, n_sigma]` -- útil
    para una visualización robusta sin que un solo píxel extremo domine
    la escala; `clip=False` devuelve el z-score sin recortar."""
    if center not in ("median", "mean"):
        raise ValueError("center debe ser 'median' o 'mean'")
    values = data.astype(np.float64)
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no hay píxeles finitos para normalizar")
    median = float(np.median(finite))
    center_value = median if center == "median" else float(np.mean(finite))
    mad = float(np.median(np.abs(finite - median)))
    sigma = max(mad * _MAD_TO_SIGMA, 1e-12)
    z_score = (values - center_value) / sigma
    return np.clip(z_score, -n_sigma, n_sigma) if clip else z_score
