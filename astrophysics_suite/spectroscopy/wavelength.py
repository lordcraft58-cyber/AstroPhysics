"""Calibración en longitud de onda -- equivalente propio de
`identify`/`reidentify` de IRAF: localizar líneas de emisión de una
lámpara de arco, ajustar la solución polinómica píxel->longitud de onda,
y trasladar esa solución a otra traza mediante correlación cruzada
(`reidentify`) sin tener que volver a identificar cada línea a mano.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from scipy import signal


@dataclass(frozen=True)
class ArcLine:
    pixel: float
    amplitude: float


def find_arc_lines(spectrum: np.ndarray, *, min_snr: float = 5.0, min_separation_px: int = 3) -> list[ArcLine]:
    """Detecta picos de línea en un espectro de lámpara de arco 1D:
    umbral de significancia sobre un fondo local robusto (mediana
    corrida) más un refinamiento de centro por centroide de 3 píxeles
    (parábola discreta) -- da precisión subpíxel sin ajustar un perfil
    completo por línea."""
    if spectrum.ndim != 1:
        raise ValueError("find_arc_lines opera sobre un espectro 1D")

    background = signal.medfilt(spectrum, kernel_size=min(101, _odd(spectrum.size)))
    residual = spectrum - background
    noise = 1.4826 * np.median(np.abs(residual - np.median(residual)))
    noise = max(noise, 1e-9)

    peak_indices, _ = signal.find_peaks(residual, height=min_snr * noise, distance=min_separation_px)

    lines: list[ArcLine] = []
    for idx in peak_indices:
        if idx <= 0 or idx >= spectrum.size - 1:
            continue
        y_left, y_center, y_right = residual[idx - 1], residual[idx], residual[idx + 1]
        denominator = y_left - 2 * y_center + y_right
        subpixel_shift = 0.5 * (y_left - y_right) / denominator if denominator != 0 else 0.0
        subpixel_shift = float(np.clip(subpixel_shift, -1.0, 1.0))
        lines.append(ArcLine(pixel=float(idx) + subpixel_shift, amplitude=float(residual[idx])))
    return lines


def _odd(n: int) -> int:
    return n if n % 2 == 1 else n - 1


@dataclass(frozen=True)
class WavelengthSolution:
    coefficients: np.ndarray
    """Coeficientes de `numpy.polyval` (grado descendente), píxel ->
    longitud de onda."""
    degree: int
    rms_residual: float
    residuals: np.ndarray
    reference_pixel_shift: float = 0.0
    """Desplazamiento (píxeles) aplicado antes de evaluar -- distinto de
    cero solo tras `reidentify_wavelength_solution`."""

    def pixel_to_wavelength(self, pixel: np.ndarray | float) -> np.ndarray | float:
        return np.polyval(self.coefficients, np.asarray(pixel) - self.reference_pixel_shift)


def fit_wavelength_solution(
    pixel_centers: list[float], known_wavelengths: list[float], *, degree: int = 3
) -> WavelengthSolution:
    """Ajusta el polinomio píxel -> longitud de onda (equivalente al
    ajuste final de `identify`) a partir de líneas ya emparejadas contra
    un catálogo de referencia."""
    n = len(pixel_centers)
    if n != len(known_wavelengths):
        raise ValueError("pixel_centers y known_wavelengths deben tener la misma longitud")
    if n < degree + 1:
        raise ValueError(f"se necesitan al menos {degree + 1} líneas para un ajuste de grado {degree}; hay {n}")

    pixels = np.asarray(pixel_centers, dtype=np.float64)
    wavelengths = np.asarray(known_wavelengths, dtype=np.float64)
    coefficients = np.polyfit(pixels, wavelengths, deg=degree)
    predicted = np.polyval(coefficients, pixels)
    residuals = wavelengths - predicted
    rms = float(math.sqrt(np.mean(residuals**2)))

    return WavelengthSolution(coefficients=coefficients, degree=degree, rms_residual=rms, residuals=residuals)


def reidentify_wavelength_solution(
    reference_solution: WavelengthSolution,
    reference_spectrum: np.ndarray,
    new_spectrum: np.ndarray,
    *,
    max_shift_px: int = 50,
) -> WavelengthSolution:
    """Traslada una solución ya identificada a un nuevo espectro de arco
    (misma configuración instrumental, pequeño desplazamiento mecánico
    entre exposiciones) por correlación cruzada -- sin volver a
    identificar línea por línea, igual que `reidentify` de IRAF cuando el
    desplazamiento es puramente una traslación en píxeles.
    """
    if reference_spectrum.shape != new_spectrum.shape:
        raise ValueError("reference_spectrum y new_spectrum deben tener la misma longitud")

    ref = reference_spectrum - np.median(reference_spectrum)
    new = new_spectrum - np.median(new_spectrum)
    correlation = signal.correlate(new, ref, mode="full")
    lags = signal.correlation_lags(new.size, ref.size, mode="full")

    window = (lags >= -max_shift_px) & (lags <= max_shift_px)
    if not np.any(window):
        raise ValueError("max_shift_px es demasiado pequeño para el tamaño del espectro")
    windowed_lags, windowed_corr = lags[window], correlation[window]

    peak_idx = int(np.argmax(windowed_corr))
    if 0 < peak_idx < len(windowed_corr) - 1:
        y_left, y_center, y_right = windowed_corr[peak_idx - 1 : peak_idx + 2]
        denominator = y_left - 2 * y_center + y_right
        subpixel = 0.5 * (y_left - y_right) / denominator if denominator != 0 else 0.0
    else:
        subpixel = 0.0
    shift_px = float(windowed_lags[peak_idx]) + float(np.clip(subpixel, -1.0, 1.0))

    return WavelengthSolution(
        coefficients=reference_solution.coefficients,
        degree=reference_solution.degree,
        rms_residual=reference_solution.rms_residual,
        residuals=reference_solution.residuals,
        reference_pixel_shift=shift_px,
    )
