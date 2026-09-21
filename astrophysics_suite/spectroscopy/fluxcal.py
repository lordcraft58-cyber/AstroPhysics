"""Calibración en flujo -- equivalente propio de `standard`/`sensfunc`/
`calibrate` de IRAF: masa de aire, corrección de extinción atmosférica,
función de sensibilidad instrumental desde una estrella estándar, y
aplicación de esa función a un espectro científico.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np


def compute_airmass_kasten_young(zenith_angle_deg: float) -> float:
    """Masa de aire -- fórmula empírica de Kasten & Young (1989, Applied
    Optics 28, 4735), notablemente más precisa que la secante plano-
    paralela cerca del horizonte (secante diverge a infinito en z=90°;
    Kasten-Young converge a un valor finito realista, ~38 en el
    horizonte, y coincide con la secante para z pequeño donde ambas son
    válidas).
    """
    if not (0.0 <= zenith_angle_deg < 90.0):
        raise ValueError("zenith_angle_deg debe estar en [0, 90)")
    z = zenith_angle_deg
    cos_z = math.cos(math.radians(z))
    return 1.0 / (cos_z + 0.50572 * (96.07995 - z) ** -1.6364)


def compute_airmass_secant(zenith_angle_deg: float) -> float:
    """Aproximación plano-paralela clásica -- válida y suficiente para
    `z < ~60°`; se conserva junto a Kasten-Young para comparación y para
    reproducir pipelines heredados que asumen esta fórmula."""
    if not (0.0 <= zenith_angle_deg < 90.0):
        raise ValueError("zenith_angle_deg debe estar en [0, 90)")
    return 1.0 / math.cos(math.radians(zenith_angle_deg))


def apply_extinction_correction(
    flux: np.ndarray, *, extinction_mag_per_airmass: float, airmass: float
) -> np.ndarray:
    """Corrige un espectro observado por extinción atmosférica: el flujo
    verdadero por encima de la atmósfera es mayor que el observado en un
    factor `10^(0.4 * k * X)`, donde `k` es el coeficiente de extinción
    (mag/masa de aire) y `X` la masa de aire de la observación."""
    if airmass <= 0:
        raise ValueError("airmass debe ser positivo")
    return flux * 10.0 ** (0.4 * extinction_mag_per_airmass * airmass)


@dataclass(frozen=True)
class SensitivityFunction:
    wavelength: np.ndarray
    sensitivity: np.ndarray
    """Factor multiplicativo por el que se escala una tasa de cuentas
    (ADU/s) medida para obtener flujo físico (p. ej. erg/s/cm^2/Å)."""
    poly_degree: int
    fit_coefficients: np.ndarray
    """Coeficientes de un ajuste polinómico suave a `log10(sensitivity)`
    frente a la longitud de onda -- la propia función de sensibilidad
    medida es ruidosa punto a punto; lo que se aplica en la práctica es
    el ajuste suavizado, igual que hace `sensfunc`."""

    def evaluate(self, wavelength: np.ndarray | float) -> np.ndarray | float:
        return 10.0 ** np.polyval(self.fit_coefficients, np.asarray(wavelength))


def build_sensitivity_function(
    observed_wavelength: np.ndarray,
    observed_counts_per_s: np.ndarray,
    reference_wavelength: np.ndarray,
    reference_flux: np.ndarray,
    *,
    airmass: float,
    extinction_mag_per_airmass: float = 0.0,
    poly_degree: int = 5,
) -> SensitivityFunction:
    """Construye la función de sensibilidad a partir del espectro
    observado (cuentas/s) de una estrella estándar y su espectro de
    referencia conocido (flujo físico, sobre la misma rejilla de
    longitud de onda del catálogo de estándares -- interpolar antes si
    no coinciden). Corrige primero por extinción atmosférica a la masa
    de aire de la observación, luego ajusta `log10(sensibilidad)` con un
    polinomio para suavizar el ruido punto a punto.
    """
    if observed_wavelength.shape != observed_counts_per_s.shape:
        raise ValueError("observed_wavelength y observed_counts_per_s deben tener la misma forma")
    if reference_wavelength.shape != reference_flux.shape:
        raise ValueError("reference_wavelength y reference_flux deben tener la misma forma")

    reference_flux_on_observed_grid = np.interp(observed_wavelength, reference_wavelength, reference_flux)
    corrected_counts = apply_extinction_correction(
        observed_counts_per_s, extinction_mag_per_airmass=extinction_mag_per_airmass, airmass=airmass
    )
    valid = corrected_counts > 0
    if np.count_nonzero(valid) < poly_degree + 1:
        raise ValueError("no hay suficientes puntos con señal positiva para ajustar la función de sensibilidad")

    sensitivity_raw = reference_flux_on_observed_grid[valid] / corrected_counts[valid]
    log_sensitivity = np.log10(sensitivity_raw)
    coefficients = np.polyfit(observed_wavelength[valid], log_sensitivity, deg=poly_degree)

    return SensitivityFunction(
        wavelength=observed_wavelength[valid],
        sensitivity=sensitivity_raw,
        poly_degree=poly_degree,
        fit_coefficients=coefficients,
    )


def calibrate_flux(
    wavelength: np.ndarray,
    counts_per_s: np.ndarray,
    sensitivity: SensitivityFunction,
    *,
    airmass: float,
    extinction_mag_per_airmass: float = 0.0,
) -> np.ndarray:
    """Aplica la función de sensibilidad (y la corrección de extinción a
    la masa de aire de la observación científica, que en general no
    coincide con la de la estándar) para convertir un espectro científico
    de cuentas/s a flujo físico."""
    corrected_counts = apply_extinction_correction(
        counts_per_s, extinction_mag_per_airmass=extinction_mag_per_airmass, airmass=airmass
    )
    return corrected_counts * sensitivity.evaluate(wavelength)
