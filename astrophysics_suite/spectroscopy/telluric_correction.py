"""Corrección real de absorción telúrica (§46) -- división por la
transmisión atmosférica medida en un espectro real de estrella estándar
telúrica (normalmente una A0V u otra estrella caliente de continuo
suave), escalada por la razón de masas de aire entre la exposición
científica y la de la estándar.

Continúa explícitamente el hallazgo documentado en `telluric_lines.py`
(Slice 6): ese módulo SOLO identifica solape de bandas conocidas y
declara verbatim *"ninguna corrección/sustracción telúrica se implementa
aquí todavía; eso exigiría un espectro de estrella estándar telúrica"*.
Este módulo es esa corrección real.

Física: la profundidad óptica telúrica escala linealmente con la masa de
aire (ley de Beer-Lambert de una atmósfera plano-paralela, aproximación
estándar para masas de aire moderadas). Si `T_std(λ)` es la transmisión
medida (espectro de la estándar normalizado por SU PROPIO continuo, para
aislar la atmósfera de la forma espectral intrínseca de la estrella) a
masa de aire `X_std`, la transmisión esperada en la exposición científica
a masa de aire `X_sci` es `T_std(λ) ** (X_sci / X_std)` -- se divide el
flujo científico por ese factor.

Disciplina de honestidad (misma que en el resto del proyecto): la
corrección SOLO se aplica dentro de las bandas telúricas catalogadas en
`telluric_lines.TELLURIC_BANDS` -- nunca en todo el rango cubierto por la
estándar, porque fuera de esas bandas una supuesta "transmisión" medida
sería en realidad líneas fotosféricas propias de la estrella estándar (o
ruido de su continuo), no atmósfera, y aplicarla ahí contaminaría el
espectro científico con features que no le pertenecen. El resultado
siempre devuelve el factor de corrección aplicado punto a punto y una
máscara de qué píxeles se corrigieron de verdad -- nunca se elimina nada
"en silencio".
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.continuum import fit_continuum, normalize_by_continuum
from astrophysics_suite.spectroscopy.telluric_lines import TelluricBand, bands_overlapping_range


@dataclass(frozen=True)
class TelluricStandardTransmission:
    wavelength: np.ndarray
    transmission: np.ndarray
    """Espectro de la estándar dividido por su propio continuo ajustado
    (`continuum.fit_continuum(..., reject="both")`) -- ~1.0 fuera de
    absorciones reales (telúricas o fotosféricas de la propia estrella),
    <1.0 dentro."""
    continuum_rms_residual: float


def measure_standard_transmission(
    wavelength: np.ndarray,
    flux: np.ndarray,
    *,
    continuum_degree: int = 4,
    continuum_sigma_clip: float = 2.5,
    continuum_max_iters: int = 10,
) -> TelluricStandardTransmission:
    """Normaliza el espectro REAL de la estrella estándar por su propio
    continuo, para aislar la transmisión atmosférica de su forma
    espectral intrínseca. `reject="both"` dentro de `fit_continuum`
    excluye iterativamente tanto las bandas telúricas profundas como
    cualquier línea fotosférica propia de la estrella del ajuste del
    continuo -- ninguna profundidad se inventa, se mide directamente del
    espectro dado."""
    if wavelength.shape != flux.shape:
        raise ValueError("wavelength y flux deben tener la misma forma")
    fit = fit_continuum(
        wavelength, flux, degree=continuum_degree, sigma_clip=continuum_sigma_clip,
        max_iters=continuum_max_iters, reject="both",
    )
    transmission = normalize_by_continuum(flux, fit)
    return TelluricStandardTransmission(
        wavelength=wavelength, transmission=transmission, continuum_rms_residual=fit.rms_residual,
    )


@dataclass(frozen=True)
class TelluricCorrectionResult:
    corrected_flux: np.ndarray
    correction_factor: np.ndarray
    """Divisor real aplicado en cada píxel -- `1.0` donde no se aplicó
    ninguna corrección (fuera de banda telúrica catalogada, o fuera de la
    cobertura en longitud de onda de la estándar)."""
    corrected_mask: np.ndarray
    """`True` donde sí se aplicó una corrección real."""
    bands_used: tuple[TelluricBand, ...]
    airmass_ratio: float


def correct_telluric_absorption(
    science_wavelength: np.ndarray,
    science_flux: np.ndarray,
    *,
    standard_transmission: TelluricStandardTransmission,
    science_airmass: float,
    standard_airmass: float,
    min_transmission: float = 0.05,
) -> TelluricCorrectionResult:
    """Divide `science_flux` por la transmisión atmosférica real medida
    en `standard_transmission`, escalada por la razón de masas de aire, y
    SOLO dentro de las bandas telúricas catalogadas que la estándar
    realmente cubre en longitud de onda.

    `min_transmission` acota por debajo el divisor (una transmisión medida
    arbitrariamente cercana a cero, por ruido del continuo de la
    estándar, no debe disparar el flujo corregido a un valor arbitrariamente
    grande) -- el propio catálogo de bandas ya documenta que la
    profundidad real depende de condiciones concretas, así que un tope
    conservador es más honesto que una división sin límite.
    """
    if science_wavelength.shape != science_flux.shape:
        raise ValueError("science_wavelength y science_flux deben tener la misma forma")
    if science_airmass <= 0:
        raise ValueError("science_airmass debe ser > 0")
    if standard_airmass <= 0:
        raise ValueError("standard_airmass debe ser > 0")

    std_wavelength = standard_transmission.wavelength
    std_min, std_max = float(std_wavelength.min()), float(std_wavelength.max())

    bands_used = bands_overlapping_range(std_min, std_max)

    correction_factor = np.ones_like(science_flux, dtype=np.float64)
    corrected_mask = np.zeros(science_flux.shape, dtype=bool)
    airmass_ratio = science_airmass / standard_airmass

    if bands_used:
        in_band = np.zeros(science_wavelength.shape, dtype=bool)
        for band in bands_used:
            in_band |= (science_wavelength >= band.wavelength_start_angstrom) & (
                science_wavelength <= band.wavelength_end_angstrom
            )
        in_standard_coverage = (science_wavelength >= std_min) & (science_wavelength <= std_max)
        apply_mask = in_band & in_standard_coverage

        if np.any(apply_mask):
            transmission_at_science = np.interp(
                science_wavelength[apply_mask], std_wavelength, standard_transmission.transmission,
            )
            transmission_at_science = np.clip(transmission_at_science, min_transmission, None)
            correction_factor[apply_mask] = transmission_at_science ** airmass_ratio
            corrected_mask[apply_mask] = True

    with np.errstate(divide="ignore", invalid="ignore"):
        corrected_flux = science_flux / correction_factor

    return TelluricCorrectionResult(
        corrected_flux=corrected_flux, correction_factor=correction_factor, corrected_mask=corrected_mask,
        bands_used=bands_used, airmass_ratio=airmass_ratio,
    )
