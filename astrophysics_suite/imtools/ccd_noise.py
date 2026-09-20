"""Incertidumbre real de una imagen CCD en ADU: ruido de disparo
(Poisson, que actúa sobre ELECTRONES reales, no sobre cuentas ADU) más
ruido de lectura, convertido de vuelta a ADU con la ganancia real del
instrumento.

Fórmula estándar de reducción CCD (la misma ya usada internamente por
`imtools.cosmic_rays` para L.A.Cosmic, extraída aquí para que cualquier
otro consumidor -- la GUI de espectroscopía incluida -- la reutilice en
vez de aproximar con `sqrt(ADU)` (válido solo si `gain=1` e-/ADU y sin
ruido de lectura, una aproximación mucho más burda que rara vez es
cierta para una cámara real).
"""
from __future__ import annotations

import numpy as np


def ccd_noise_adu(data_adu: np.ndarray, *, gain_e_per_adu: float, read_noise_e: float = 0.0) -> np.ndarray:
    """`sqrt(señal_e + ruido_lectura_e²) / ganancia` -- la incertidumbre
    total esperada en ADU. `gain_e_per_adu`/`read_noise_e` deben ser
    valores REALES del instrumento (típicamente `header['GAIN']`/
    `header['RDNOISE']`); nunca se inventan aquí -- el llamador decide
    qué hacer si no dispone de ellos (normalmente, caer a la
    aproximación `sqrt(ADU)`)."""
    if gain_e_per_adu <= 0:
        raise ValueError("gain_e_per_adu debe ser positivo")
    if read_noise_e < 0:
        raise ValueError("read_noise_e no puede ser negativo")
    signal_e = np.clip(data_adu, a_min=0.0, a_max=None) * gain_e_per_adu
    noise_e = np.sqrt(signal_e + read_noise_e**2)
    return np.clip(noise_e / gain_e_per_adu, a_min=1e-6, a_max=None)
