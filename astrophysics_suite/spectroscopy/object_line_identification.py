"""Identificación automática de líneas de objeto tras calibrar (§21,
§22): detecta desviaciones reales del continuo en un espectro YA
calibrado en longitud de onda, y las contrasta contra un catálogo de
líneas conocidas por posición REAL -- a diferencia de la lámpara de
arco (`wavelength.match_lines_to_catalog`), donde solo se dispone de
una dispersión aproximada, aquí ya existe una calibración real que usar
directamente, sin necesidad de predecir nada.

SUGERENCIAS únicamente, mismo principio que en todo el proyecto (§10):
nunca se acepta una identificación dudosa sin confirmación explícita del
llamador -- la GUI decide qué hacer con `confidence`/`line_type_agrees`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.line_catalog import LineType, SpectralLine
from astrophysics_suite.spectroscopy.telluric_lines import TelluricBand, find_telluric_overlap
from astrophysics_suite.spectroscopy.wavelength import ArcLine, find_arc_lines


def detect_object_lines(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    *,
    min_snr: float = 5.0,
    min_separation_angstrom: float = 2.0,
) -> list[tuple[float, float]]:
    """Detecta desviaciones reales del continuo (emisión Y absorción) --
    dos pasadas reales de `wavelength.find_arc_lines` (mismo detector de
    picos sobre fondo local robusto, ya probado): una sobre el residuo
    tal cual (picos positivos = emisión) y otra sobre el residuo negado
    (picos positivos ahí = depresiones reales = absorción).

    Deliberadamente NO se usa `abs(residuo)` en una sola pasada: el
    valor absoluto de un ruido gaussiano real es una distribución
    semi-normal (siempre >= 0, con una cola distinta), y el umbral de
    significancia de `find_arc_lines` (MAD del propio array de entrada)
    deja de corresponder a `min_snr` sigmas reales del ruido original --
    en la práctica dispara falsos positivos muy por encima de lo que
    `min_snr` promete. Dos pasadas sobre el residuo con signo (y su
    negado) preservan la estadística gaussiana real en cada una.

    Devuelve `[(wavelength_reales, amplitud_con_signo), ...]` -- nunca
    inventa una línea donde no hay una desviación real medible."""
    if wavelength.shape != flux.shape or wavelength.shape != continuum.shape:
        raise ValueError("wavelength, flux y continuum deben tener la misma forma")
    if wavelength.size < 5:
        return []

    residual = flux - continuum
    valid = np.isfinite(residual)
    if np.count_nonzero(valid) < 5:
        return []

    median_step = float(np.median(np.abs(np.diff(wavelength[valid])))) if np.count_nonzero(valid) > 1 else 1.0
    min_separation_px = max(1, int(round(min_separation_angstrom / max(median_step, 1e-9))))

    # `find_arc_lines` no tolera NaN -- se rellenan con 0.0 SOLO para la
    # detección de picos (nunca se reporta un pico ahí: un hueco inválido
    # no puede producir un cruce de umbral real salvo que sus vecinos
    # también lo hagan, y en ese caso la posición reportada seguirá
    # siendo la de un vecino finito real).
    safe_residual = np.where(valid, residual, 0.0)
    emission_peaks: list[ArcLine] = find_arc_lines(safe_residual, min_snr=min_snr, min_separation_px=min_separation_px)
    absorption_peaks: list[ArcLine] = find_arc_lines(-safe_residual, min_snr=min_snr, min_separation_px=min_separation_px)

    indices = np.arange(wavelength.size, dtype=np.float64)
    results: list[tuple[float, float]] = []
    for line, sign in [(p, 1.0) for p in emission_peaks] + [(p, -1.0) for p in absorption_peaks]:
        nearest = int(round(line.pixel))
        nearest = max(0, min(wavelength.size - 1, nearest))
        if not valid[nearest]:
            continue
        real_wavelength = float(np.interp(line.pixel, indices, wavelength))
        signed_amplitude = sign * float(line.amplitude)
        results.append((real_wavelength, signed_amplitude))
    results.sort(key=lambda item: item[0])
    return results


@dataclass(frozen=True)
class ObjectLineMatch:
    detected_wavelength: float
    detected_amplitude: float
    """Amplitud real (con signo) del residuo detectado -- negativa para
    una depresión (absorción), positiva para una elevación (emisión)."""
    catalog_line: SpectralLine
    residual_angstrom: float
    """`detected_wavelength - catalog_line.wavelength_air_angstrom`."""
    confidence: float
    """En [0,1]: `1 - |residual|/tolerance_angstrom`, recortado --
    cercanía a la posición del catálogo, NO una probabilidad
    estadística."""
    line_type_agrees: bool
    """`True` si el signo de la amplitud detectada concuerda con
    `catalog_line.line_type` -- `False` avisa de una coincidencia de
    POSICIÓN cuya naturaleza no encaja (p. ej. una depresión real
    emparejada con una línea catalogada como emisión), sin descartarla:
    el llamador decide."""
    telluric_overlap: TelluricBand | None
    """Banda telúrica real que solapa esta longitud de onda, o `None` --
    nunca corrige ni elimina nada (§46), solo avisa."""


def identify_object_lines_in_spectrum(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    catalog: tuple[SpectralLine, ...],
    *,
    min_snr: float = 5.0,
    min_separation_angstrom: float = 2.0,
    tolerance_angstrom: float = 3.0,
    flag_telluric: bool = True,
) -> tuple[ObjectLineMatch, ...]:
    """Detecta líneas reales y sugiere, para cada una, la línea de
    catálogo más cercana dentro de `tolerance_angstrom` -- una detección
    sin ninguna línea de catálogo lo bastante cerca se omite (§10/§21:
    nunca se inventa a qué corresponde una detección real sin evidencia
    de catálogo, igual que `line_catalog.match_lines_to_catalog` omite
    una sugerencia sin coincidencia).
    """
    if tolerance_angstrom <= 0:
        raise ValueError("tolerance_angstrom debe ser positivo")
    if not catalog:
        raise ValueError("catalog está vacío -- no hay nada contra lo que emparejar")

    detections = detect_object_lines(
        wavelength, flux, continuum, min_snr=min_snr, min_separation_angstrom=min_separation_angstrom
    )
    catalog_wavelengths = [line.wavelength_air_angstrom for line in catalog]

    matches: list[ObjectLineMatch] = []
    for detected_wavelength, amplitude in detections:
        best_line, best_residual = None, np.inf
        for line, catalog_wavelength in zip(catalog, catalog_wavelengths):
            residual = detected_wavelength - catalog_wavelength
            if abs(residual) < abs(best_residual):
                best_line, best_residual = line, residual
        if best_line is None or abs(best_residual) > tolerance_angstrom:
            continue
        confidence = max(0.0, 1.0 - abs(best_residual) / tolerance_angstrom)
        line_type_agrees = (amplitude < 0) == (best_line.line_type is LineType.ABSORPTION)
        telluric = find_telluric_overlap(detected_wavelength) if flag_telluric else None
        matches.append(ObjectLineMatch(
            detected_wavelength=detected_wavelength, detected_amplitude=amplitude, catalog_line=best_line,
            residual_angstrom=best_residual, confidence=confidence, line_type_agrees=line_type_agrees,
            telluric_overlap=telluric,
        ))
    return tuple(matches)
