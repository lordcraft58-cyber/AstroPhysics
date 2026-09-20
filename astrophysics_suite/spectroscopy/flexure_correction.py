"""Corrección de flexión/deriva espectral entre exposiciones (§44):
recalcula SOLO el desplazamiento global (Δpíxel/Δλ/Δvelocidad) entre dos
exposiciones de la misma configuración instrumental por correlación
cruzada -- reutiliza `wavelength.reidentify_wavelength_solution` (Fase
15, ya probado), nunca recalcula innecesariamente el polinomio completo
de la solución instrumental sin nueva evidencia de líneas.

Aplicable con dos espectros de arco, o -- cuando no se dispone de una
segunda exposición de arco -- con cualquier par de espectros que
compartan una referencia de posición fija entre exposiciones: líneas
telúricas reales (la atmósfera terrestre no se mueve entre exposiciones
de la misma noche, `telluric_lines.py`, Slice 6) o el canal de
calibración lateral/simultánea (`lateral_calibration.py`, Slice 3) si el
instrumento lo tiene. La elección de qué usar como referencia es
responsabilidad del llamador -- este módulo no asume cuál.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.radial_velocity import velocity_from_wavelength_shift
from astrophysics_suite.spectroscopy.wavelength import WavelengthSolution, reidentify_wavelength_solution


@dataclass(frozen=True)
class FlexureShift:
    shift_px: float
    """Desplazamiento global real recuperado por correlación cruzada --
    la forma del polinomio de la solución instrumental no cambia."""
    shift_angstrom: float
    """`shift_px` convertido a Å usando la dispersión LOCAL real de la
    solución original en `reference_wavelength` (derivada numérica en
    ese punto, no una dispersión media global asumida)."""
    shift_velocity_km_s: float
    """Mismo desplazamiento expresado como velocidad Doppler equivalente
    (`radial_velocity.velocity_from_wavelength_shift`, convención
    clásica) -- una forma más intuitiva de juzgar si la deriva importa
    para la ciencia que se esté haciendo."""
    reference_wavelength: float
    shifted_solution: WavelengthSolution
    """La solución original con SOLO `reference_pixel_shift` actualizado
    -- lista para usar en `pixel_to_wavelength`, sin reajustar nada más."""


def _local_dispersion_angstrom_per_px(solution: WavelengthSolution, n_pixels: int, reference_wavelength: float) -> float:
    """Dispersión real (dλ/dpíxel) de `solution` en `reference_wavelength`
    -- por diferencia finita centrada alrededor del píxel real que
    corresponde a esa longitud de onda bajo la solución ORIGINAL (no
    asumida: se invierte por interpolación sobre la propia solución
    evaluada en toda la traza)."""
    pixels = np.arange(n_pixels, dtype=np.float64)
    wavelengths = np.asarray(solution.pixel_to_wavelength(pixels), dtype=np.float64)
    if not (np.all(np.diff(wavelengths) > 0) or np.all(np.diff(wavelengths) < 0)):
        raise ValueError(
            "la solución de longitud de onda no es monótona sobre el rango de píxeles dado -- "
            "no se puede invertir de forma unívoca para hallar la dispersión local"
        )
    reference_pixel = float(np.interp(reference_wavelength, wavelengths, pixels) if wavelengths[0] < wavelengths[-1]
                             else np.interp(reference_wavelength, wavelengths[::-1], pixels[::-1]))
    delta = 0.5
    return float(
        (solution.pixel_to_wavelength(reference_pixel + delta) - solution.pixel_to_wavelength(reference_pixel - delta))
        / (2 * delta)
    )


def measure_flexure_shift(
    reference_solution: WavelengthSolution,
    reference_spectrum: np.ndarray,
    new_spectrum: np.ndarray,
    *,
    reference_wavelength: float,
    max_shift_px: int = 50,
) -> FlexureShift:
    """Mide la deriva real entre `reference_spectrum` (el espectro sobre
    el que `reference_solution` se validó) y `new_spectrum` (una
    exposición posterior de la misma configuración instrumental), y
    devuelve el desplazamiento en las tres unidades que pide el encargo
    (§44: "Δpixel/Δλ/Δvelocidad").

    `reference_wavelength` fija dónde se evalúa la dispersión local para
    convertir píxeles a Å -- normalmente el centro de la región
    científica de interés, no necesariamente el centro del detector.

    `reference_solution` debe ser la solución "base" (normalmente con
    `reference_pixel_shift == 0`, tal como sale de `fit_wavelength_
    solution` o de `SpectralCalibrationProfile.to_solution()`) -- igual
    que `reidentify_wavelength_solution`, de la que este motor depende
    directamente, el desplazamiento medido reemplaza cualquier
    `reference_pixel_shift` previo en vez de acumularse con él. Para una
    serie larga de exposiciones, comparar siempre contra la exposición
    de referencia original (no encadenar exposición-a-exposición) evita
    acumular error.
    """
    if reference_spectrum.shape != new_spectrum.shape:
        raise ValueError("reference_spectrum y new_spectrum deben tener la misma forma")

    shifted_solution = reidentify_wavelength_solution(
        reference_solution, reference_spectrum, new_spectrum, max_shift_px=max_shift_px
    )
    # `reidentify_wavelength_solution` fija `reference_pixel_shift` al
    # desplazamiento real medido de `reference_spectrum` a `new_spectrum`
    # -- no lo suma al de `reference_solution` -- así que ES el
    # desplazamiento real que se busca, directamente.
    shift_px = shifted_solution.reference_pixel_shift

    local_dispersion = _local_dispersion_angstrom_per_px(
        reference_solution, reference_spectrum.size, reference_wavelength
    )
    shift_angstrom = shift_px * local_dispersion
    shift_velocity = float(
        velocity_from_wavelength_shift(reference_wavelength + shift_angstrom, reference_wavelength)
    )

    return FlexureShift(
        shift_px=shift_px, shift_angstrom=shift_angstrom, shift_velocity_km_s=shift_velocity,
        reference_wavelength=reference_wavelength, shifted_solution=shifted_solution,
    )
