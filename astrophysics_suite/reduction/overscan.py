"""Corrección de overscan y recorte -- equivalente propio de la parte de
`ccdproc`/`colbias` de IRAF que modela y sustrae el nivel de bias
electrónico leído en la franja de sobrebarrido de cada exposición
(más estable que usar un bias maestro tomado en otro momento para ese
componente en particular, porque se mide en la misma lectura).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class OverscanResult:
    data: np.ndarray
    """La imagen (recortada si se pidió `trim_region`) tras sustraer el
    nivel de overscan modelado."""
    overscan_level: np.ndarray
    """El perfil de overscan sustraído -- un valor por fila (o columna,
    según `fit_axis`), antes de recortar la imagen."""


def subtract_overscan(
    data: np.ndarray,
    *,
    overscan_region: tuple[slice, slice],
    trim_region: tuple[slice, slice] | None = None,
    fit_axis: int = 0,
    function: str = "median",
    poly_degree: int = 3,
) -> OverscanResult:
    """Modela el nivel de overscan a lo largo de `fit_axis` (0 = una
    fila por cada fila de la imagen, típico cuando la franja de overscan
    corre en columnas; 1 = lo simétrico) y lo sustrae de toda la imagen
    por difusión (broadcast).

    `function`:
      - "median"/"mean": un único valor por línea de `fit_axis` (el
        overscan de esa fila/columna), sin suavizado adicional.
      - "polynomial": ajusta un polinomio de grado `poly_degree` al
        perfil anterior a lo largo de `fit_axis`, para suprimir el ruido
        de lectura de ese perfil (el propio IRAF ofrece esto vía
        `function=legendre/chebyshev/spline3/poly`; aquí se reimplementa
        con `numpy.polyfit`, suficiente para el caso general -- splines
        quedan fuera de alcance por ahora).
    """
    if fit_axis not in (0, 1):
        raise ValueError("fit_axis debe ser 0 o 1")
    if function not in ("median", "mean", "polynomial"):
        raise ValueError(f"function debe ser 'median', 'mean' o 'polynomial'; recibido {function!r}")

    overscan_strip = data[overscan_region].astype(np.float64)
    collapse_axis = 1 - fit_axis
    if function == "median":
        profile = np.median(overscan_strip, axis=collapse_axis)
    else:
        profile = np.mean(overscan_strip, axis=collapse_axis)

    if function == "polynomial":
        n = profile.size
        if n <= poly_degree:
            raise ValueError(f"poly_degree={poly_degree} requiere más de {poly_degree} muestras de overscan; hay {n}")
        x = np.arange(n, dtype=np.float64)
        coeffs = np.polyfit(x, profile, deg=poly_degree)
        profile = np.polyval(coeffs, x)

    corrected = data.astype(np.float64).copy()
    if fit_axis == 0:
        corrected -= profile[:, np.newaxis]
    else:
        corrected -= profile[np.newaxis, :]

    if trim_region is not None:
        corrected = corrected[trim_region]

    return OverscanResult(data=corrected, overscan_level=profile)
