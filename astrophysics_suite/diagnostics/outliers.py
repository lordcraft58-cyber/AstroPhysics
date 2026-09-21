"""Marcado robusto de valores atípicos -- mediana + MAD (nunca
media/desviación estándar, que un solo outlier ya desvía), mismo
criterio que ya usan por separado `photometry.calibration.fit_zeropoint`,
`photometry.aperture`, `spectroscopy.continuum`/`trace` y
`astrometry.plate_solve._robust_fit_wcs`. Generalizado aquí solo para
DIAGNÓSTICO (qué puntos de un resultado ya ajustado son atípicos), no
para rechazo dentro de un ajuste -- eso sigue siendo responsabilidad de
cada motor.
"""
from __future__ import annotations

import numpy as np

_MAD_TO_SIGMA = 1.4826
_MIN_SIGMA_FLOOR = 1e-9


def flag_outliers(values: tuple[float, ...], *, sigma: float = 3.0) -> tuple[int, ...]:
    """Índices (no valores) de `values` cuya desviación respecto a la
    mediana supera `sigma` veces la desviación robusta (MAD escalada).
    Con menos de 2 puntos no hay MAD que calcular -- nunca ninguno."""
    if len(values) < 2:
        return ()
    arr = np.asarray(values, dtype=np.float64)
    median = float(np.median(arr))
    mad = float(np.median(np.abs(arr - median)))
    robust_sigma = max(mad * _MAD_TO_SIGMA, _MIN_SIGMA_FLOOR)
    return tuple(int(i) for i, v in enumerate(arr) if abs(v - median) > sigma * robust_sigma)
