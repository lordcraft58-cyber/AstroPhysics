"""Medición de líneas espectrales -- equivalente propio de `splot`/
`fitprofs` de IRAF: centroide, FWHM, ancho equivalente y flujo
integrado de una línea real ya localizada en un espectro extraído
(`spectroscopy/trace.py`) y calibrado en longitud de onda
(`spectroscopy/wavelength.py`), contra el continuo ya ajustado
(`spectroscopy/continuum.py::fit_continuum`).

Sigue la misma convención de arrays sueltos (`wavelength`, `flux`,
`continuum`) que ya usan esos tres módulos -- no introduce un tipo
`Spectrum` unificado (eso queda documentado como una pieza de
arquitectura mayor y separada, ver docs/audit/13-IRAF-CAPABILITY-MAP.md
§7 y 45-CIERRE-BACKLOG-PENDIENTE-MOTORES-ANTERIORES.md).

Nunca busca una línea por su cuenta: `expected_wavelength`/
`window_halfwidth` los da el llamador (una lista de líneas conocidas
del objeto, o donde el usuario marcó en la GUI) -- medir "la línea más
fuerte que haya por ahí" sin una posición esperada real inventaría qué
se está midiendo.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class LineMeasurement:
    center_wavelength: float
    """Centroide real (ponderado por |flujo - continuo| dentro de la
    ventana) -- puede diferir de `expected_wavelength` por un
    desplazamiento real (velocidad radial, calibración imperfecta)."""
    fwhm: float | None
    """Ancho a media altura del perfil sobre/bajo el continuo, en las
    mismas unidades que `wavelength`. `None` si el perfil no cruza la
    media altura dentro de la ventana (línea demasiado débil, o
    ventana demasiado estrecha para contener ambos cruces) -- nunca un
    valor extrapolado más allá de los datos reales."""
    equivalent_width: float | None
    """Convención estándar de `splot`: positivo para absorción,
    negativo para emisión (`EW = integral de (1 - flux/continuum) dλ`).
    `None` si el continuo no es positivo en toda la ventana (la
    definición de EW no tiene sentido dividiendo por un continuo
    nulo o negativo)."""
    equivalent_width_error: float | None
    integrated_flux: float
    """Integral de `(flux - continuum) dλ` -- positivo para emisión,
    negativo para absorción (signo opuesto a `equivalent_width` por
    construcción). Siempre calculable, a diferencia de `equivalent_
    width`: no depende de dividir por el continuo."""
    integrated_flux_error: float | None
    """`None` si no se dio `flux_uncertainty`."""
    window: tuple[float, float]
    n_points: int


def measure_line(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    *,
    expected_wavelength: float,
    window_halfwidth: float,
    flux_uncertainty: np.ndarray | None = None,
) -> LineMeasurement | None:
    """Mide una línea real dentro de
    `[expected_wavelength - window_halfwidth, expected_wavelength + window_halfwidth]`.

    Devuelve `None` (nunca una medida inventada) cuando la ventana cae
    fuera del rango cubierto por `wavelength`, o deja menos de 3 puntos
    dentro -- no hay con qué integrar ni centrar nada real."""
    if wavelength.shape != flux.shape or wavelength.shape != continuum.shape:
        raise ValueError("wavelength, flux y continuum deben tener la misma forma")
    if flux_uncertainty is not None and flux_uncertainty.shape != flux.shape:
        raise ValueError("flux_uncertainty debe tener la misma forma que flux")
    if window_halfwidth <= 0:
        raise ValueError("window_halfwidth debe ser positivo")

    lo, hi = expected_wavelength - window_halfwidth, expected_wavelength + window_halfwidth
    mask = (wavelength >= lo) & (wavelength <= hi)
    n_points = int(np.count_nonzero(mask))
    if n_points < 3:
        return None

    order = np.argsort(wavelength[mask])
    w = wavelength[mask][order]
    f = flux[mask][order]
    c = continuum[mask][order]
    residual = f - c

    abs_weight_sum = float(np.sum(np.abs(residual)))
    if abs_weight_sum > 0:
        center_wavelength = float(np.sum(w * np.abs(residual)) / abs_weight_sum)
    else:
        # Sin ninguna desviación real del continuo en la ventana: no hay
        # nada que centrar -- se informa la posición esperada, no una
        # inventada, con EW/flujo integrado en (o muy cerca de) cero.
        center_wavelength = float(expected_wavelength)

    fwhm = _half_max_width(w, residual)

    integrated_flux = float(np.trapezoid(residual, w))
    integrated_flux_error = None
    if flux_uncertainty is not None:
        unc = flux_uncertainty[mask][order]
        weights = np.gradient(w)
        integrated_flux_error = float(np.sqrt(np.sum((weights * unc) ** 2)))

    equivalent_width = None
    equivalent_width_error = None
    if np.all(c > 0):
        depth = 1.0 - f / c
        equivalent_width = float(np.trapezoid(depth, w))
        if flux_uncertainty is not None:
            unc = flux_uncertainty[mask][order]
            weights = np.gradient(w)
            equivalent_width_error = float(np.sqrt(np.sum((weights * unc / c) ** 2)))

    return LineMeasurement(
        center_wavelength=center_wavelength,
        fwhm=fwhm,
        equivalent_width=equivalent_width,
        equivalent_width_error=equivalent_width_error,
        integrated_flux=integrated_flux,
        integrated_flux_error=integrated_flux_error,
        window=(lo, hi),
        n_points=n_points,
    )


def _half_max_width(wavelength: np.ndarray, residual: np.ndarray) -> float | None:
    """Ancho a media altura de `|residual|` alrededor de su pico, por
    interpolación lineal entre los puntos reales que rodean cada
    cruce -- `None` si alguno de los dos cruces no cae dentro de los
    datos (el perfil real no se extrapola)."""
    abs_residual = np.abs(residual)
    peak_index = int(np.argmax(abs_residual))
    peak_value = abs_residual[peak_index]
    if peak_value <= 0:
        return None
    half_max = peak_value / 2.0

    left = _crossing(wavelength, abs_residual, peak_index, half_max, direction=-1)
    right = _crossing(wavelength, abs_residual, peak_index, half_max, direction=1)
    if left is None or right is None:
        return None
    return float(right - left)


def _crossing(wavelength: np.ndarray, abs_residual: np.ndarray, peak_index: int, half_max: float, *, direction: int) -> float | None:
    index = peak_index
    n = len(wavelength)
    while 0 <= index + direction < n:
        next_index = index + direction
        if abs_residual[next_index] <= half_max:
            v0, v1 = abs_residual[index], abs_residual[next_index]
            w0, w1 = wavelength[index], wavelength[next_index]
            if v1 == v0:
                return float(w1)
            fraction = (half_max - v0) / (v1 - v0)
            return float(w0 + fraction * (w1 - w0))
        index = next_index
    return None
