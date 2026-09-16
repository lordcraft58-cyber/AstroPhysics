"""STF -- Función de Transferencia de Pantalla: auto-estiramiento NO
destructivo para visualizar datos de gran rango dinámico (un FITS
lineal de 16/32 bits parece casi negro sin esto) sin tocar nunca la
matriz científica subyacente -- la matriz de datos jamás se reescribe;
solo se deriva de ella, bajo demanda, una versión 8-bit para pantalla.

Sin dependencia de Qt a propósito: es matemática pura (numpy/scipy),
comprobable sin necesidad de un display. La traducción a `QImage` vive
en `image_window.py`.

Algoritmo: la función de transferencia de tonos medios (MTF) más un
punto de corte de sombras derivado de estadística robusta (mediana +
MAD) -- el mismo principio que el "AutoStretch" de PixInsight (ver su
documentación de `ScreenTransferFunction`), reimplementado aquí desde la
definición matemática de la MTF, no copiado de ningún código fuente de
terceros.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy.optimize import brentq


def midtones_transfer_function(x: np.ndarray | float, m: float) -> np.ndarray | float:
    """MTF(x; m): con MTF(0)=0, MTF(1)=1 y MTF(m; m)=0.5 -- `m` ("balance
    de tonos medios") es el nivel de entrada que se transforma justo en
    el gris medio de salida; subirlo o bajarlo es lo que "levanta" o
    "hunde" los tonos medios sin mover ni las sombras ni las luces."""
    x = np.asarray(x, dtype=np.float64)
    m = float(np.clip(m, 1e-6, 1 - 1e-6))
    with np.errstate(divide="ignore", invalid="ignore"):
        result = ((m - 1.0) * x) / (((2.0 * m) - 1.0) * x - m)
    result = np.where(x <= 0.0, 0.0, result)
    result = np.where(x >= 1.0, 1.0, result)
    return result


def _solve_midtones_balance(normalized_median: float, target_background: float) -> float:
    if normalized_median <= 0.0:
        return 0.0
    if normalized_median >= 1.0:
        return 1.0

    def objective(m: float) -> float:
        return float(midtones_transfer_function(normalized_median, m)) - target_background

    # la MTF es monótona en m para x fijo en (0,1) -- brentq converge de
    # forma fiable en el intervalo abierto (evitando los extremos 0/1,
    # donde la propia función está indefinida por construcción).
    return brentq(objective, 1e-6, 1 - 1e-6, xtol=1e-10)


@dataclass(frozen=True)
class STFParams:
    black_point: float
    white_point: float
    midtones_balance: float


def compute_stf_params(
    data: np.ndarray,
    *,
    target_background: float = 0.25,
    shadows_clip_sigma: float = 2.8,
) -> STFParams:
    """Deriva los parámetros de estiramiento de una imagen a partir de
    su propia estadística robusta -- sin que el usuario tenga que fijar
    manualmente niveles de negro/blanco para cada imagen nueva (el punto
    completo de un "auto"-stretch).
    """
    finite = data[np.isfinite(data)]
    if finite.size == 0:
        raise ValueError("compute_stf_params necesita al menos un píxel finito")

    median = float(np.median(finite))
    mad = float(np.median(np.abs(finite - median)))
    sigma = mad * 1.4826
    data_min, data_max = float(np.min(finite)), float(np.max(finite))

    black_point = max(median - shadows_clip_sigma * sigma, data_min)
    white_point = max(data_max, black_point + 1e-12)

    denom = white_point - black_point
    normalized_median = float(np.clip((median - black_point) / denom, 0.0, 1.0)) if denom > 0 else 0.0
    midtones_balance = _solve_midtones_balance(normalized_median, target_background)

    return STFParams(black_point=black_point, white_point=white_point, midtones_balance=midtones_balance)


def apply_stf(data: np.ndarray, params: STFParams) -> np.ndarray:
    """Aplica el estiramiento -- devuelve un array float en `[0, 1]`,
    listo para escalar a 8 bits para pantalla. Nunca modifica `data`."""
    denom = params.white_point - params.black_point
    if denom <= 0:
        normalized = np.zeros_like(data, dtype=np.float64)
    else:
        normalized = np.clip((data - params.black_point) / denom, 0.0, 1.0)
    return midtones_transfer_function(normalized, params.midtones_balance)


def stf_to_uint8(data: np.ndarray, params: STFParams) -> np.ndarray:
    """Conveniencia: estiramiento + cuantización a 8 bits para pantalla."""
    stretched = apply_stf(data, params)
    return np.clip(stretched * 255.0 + 0.5, 0, 255).astype(np.uint8)
