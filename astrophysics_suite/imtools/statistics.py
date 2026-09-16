"""Estadísticas e histograma de imagen -- utilidad genérica de inspección
(equivalente propio de la parte de estadística de imagen completa de
`imstatistics`/`astutil` de IRAF), reutilizable por cualquier motor o por
la GUI sin depender de una fuente puntual ni de una apertura concreta,
a diferencia de las estadísticas locales que ya calcula
`photometry.aperture.estimate_local_sky`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class ImageStatistics:
    n_pixels: int
    mean: float
    median: float
    std: float
    mad_sigma: float
    """Desviación robusta (MAD * 1.4826) -- menos sensible que `std` a
    colas pesadas (rayos cósmicos, saturación, fuentes brillantes)."""
    minimum: float
    maximum: float
    percentile_1: float
    percentile_5: float
    percentile_95: float
    percentile_99: float


def compute_image_statistics(data: np.ndarray) -> ImageStatistics:
    """Resume `data` completa -- los valores no finitos (NaN/inf, p. ej.
    de una máscara de píxeles inválidos ya marcada como tal) se excluyen,
    nunca se cuentan como cero ni contaminan el resultado."""
    values = np.asarray(data, dtype=np.float64).ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no hay píxeles finitos para calcular estadísticas")
    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    p1, p5, p95, p99 = np.percentile(finite, [1, 5, 95, 99])
    return ImageStatistics(
        n_pixels=int(finite.size),
        mean=float(np.mean(finite)),
        median=median,
        std=float(np.std(finite)),
        mad_sigma=mad * _MAD_TO_SIGMA,
        minimum=float(np.min(finite)),
        maximum=float(np.max(finite)),
        percentile_1=float(p1),
        percentile_5=float(p5),
        percentile_95=float(p95),
        percentile_99=float(p99),
    )


@dataclass(frozen=True)
class Histogram:
    counts: np.ndarray
    bin_edges: np.ndarray
    """`len(bin_edges) == len(counts) + 1`, mismo convenio que `numpy.histogram`."""


def compute_histogram(data: np.ndarray, *, bins: int = 256, value_range: tuple[float, float] | None = None) -> Histogram:
    """Histograma de `data` completa (píxeles no finitos excluidos, igual
    que en `compute_image_statistics`). `value_range`, si se omite, usa
    el mínimo/máximo real de los datos -- igual que `numpy.histogram`."""
    if bins <= 0:
        raise ValueError("bins debe ser positivo")
    values = np.asarray(data, dtype=np.float64).ravel()
    finite = values[np.isfinite(values)]
    if finite.size == 0:
        raise ValueError("no hay píxeles finitos para calcular el histograma")
    counts, edges = np.histogram(finite, bins=bins, range=value_range)
    return Histogram(counts=counts, bin_edges=edges)
