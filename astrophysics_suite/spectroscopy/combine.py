"""Combinación de espectros 1D -- equivalente propio de `scombine` de
IRAF: varios espectros ya extraídos (`spectroscopy/trace.py`) y
calibrados en longitud de onda (`spectroscopy/wavelength.py`) del mismo
objeto (varias exposiciones) se remuestrean a una malla común y se
combinan en uno solo con mejor señal/ruido, con rechazo real de
valores atípicos (rayos cósmicos residuales, artefactos de una sola
exposición) por sigma-clipping.

Sigue la misma convención de arrays sueltos que `trace.py`/
`wavelength.py`/`continuum.py`/`lines.py` -- no introduce un tipo
`Spectrum` unificado (ver docs/audit/13-IRAF-CAPABILITY-MAP.md §7).

Nunca extrapola: un espectro de entrada solo contribuye en los puntos
de la malla común que caen dentro de su propio rango de longitud de
onda real. Un punto de la malla común sin ningún espectro de entrada
que lo cubra queda en `NaN` -- nunca en 0 ni en un valor inventado.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class CombinedSpectrum:
    wavelength: np.ndarray
    flux: np.ndarray
    """`NaN` en los puntos de `wavelength` que ningún espectro de
    entrada cubre real (nunca 0 inventado)."""
    flux_uncertainty: np.ndarray
    """`NaN` donde no hay forma honesta de estimarla: sin incertidumbres
    de entrada Y con un solo espectro contribuyendo en ese punto (no hay
    con qué medir la dispersión de una sola muestra)."""
    n_combined: np.ndarray
    """Número entero de espectros que sí contribuyeron en cada punto,
    tras el rechazo por sigma-clip."""
    n_rejected: np.ndarray
    """Número entero de espectros rechazados por sigma-clip en cada
    punto (0 si `sigma_clip` es `None` o había menos de 3 valores)."""
    method: str


def combine_spectra(
    wavelengths: list[np.ndarray],
    fluxes: list[np.ndarray],
    flux_uncertainties: list[np.ndarray | None] | None = None,
    *,
    reference_wavelength: np.ndarray | None = None,
    method: str = "median",
    sigma_clip: float | None = 3.0,
    max_iters: int = 5,
) -> CombinedSpectrum:
    """Remuestrea cada espectro de `wavelengths`/`fluxes` (interpolación
    lineal, sin extrapolar fuera de su propio rango) sobre
    `reference_wavelength` (por defecto, la malla del primer espectro --
    mismo criterio que `scombine` cuando no se da una malla explícita) y
    los combina punto a punto por `method` ("mean" o "median"), con
    rechazo de atípicos por sigma-clip robusto (MAD) cuando hay al menos
    3 espectros con dato real en ese punto.

    Si se dan `flux_uncertainties` y `method="mean"`, la combinación es
    una media ponderada por varianza inversa con propagación de error
    formal. En cualquier otro caso, la incertidumbre combinada se estima
    de la dispersión muestral real de los valores combinados (desviación
    estándar entre espectros dividida por raíz de n) -- nunca inventada,
    pero tampoco disponible con un único espectro contribuyendo en ese
    punto.
    """
    n_spectra = len(wavelengths)
    if len(fluxes) != n_spectra:
        raise ValueError("wavelengths y fluxes deben tener la misma longitud")
    if n_spectra < 2:
        raise ValueError("se necesitan al menos 2 espectros para combinar")
    if flux_uncertainties is not None and len(flux_uncertainties) != n_spectra:
        raise ValueError("flux_uncertainties debe tener la misma longitud que wavelengths")
    if method not in ("mean", "median"):
        raise ValueError(f"method debe ser 'mean' o 'median'; recibido {method!r}")

    for i, (w, f) in enumerate(zip(wavelengths, fluxes)):
        if w.shape != f.shape:
            raise ValueError(f"wavelengths[{i}] y fluxes[{i}] deben tener la misma forma")
        if w.size < 2:
            raise ValueError(f"wavelengths[{i}] necesita al menos 2 puntos")
        if not np.all(np.diff(w) > 0):
            raise ValueError(f"wavelengths[{i}] debe ser estrictamente creciente (salida real de una solución de longitud de onda)")
        if flux_uncertainties is not None and flux_uncertainties[i] is not None and flux_uncertainties[i].shape != f.shape:
            raise ValueError(f"flux_uncertainties[{i}] debe tener la misma forma que fluxes[{i}]")

    reference = reference_wavelength if reference_wavelength is not None else wavelengths[0]
    has_uncertainty = flux_uncertainties is not None and all(u is not None for u in flux_uncertainties)

    resampled_flux = np.full((n_spectra, reference.size), np.nan)
    resampled_unc = np.full((n_spectra, reference.size), np.nan)
    for i, (w, f) in enumerate(zip(wavelengths, fluxes)):
        in_range = (reference >= w[0]) & (reference <= w[-1])
        resampled_flux[i, in_range] = np.interp(reference[in_range], w, f)
        if has_uncertainty:
            resampled_unc[i, in_range] = np.interp(reference[in_range], w, flux_uncertainties[i])

    combined_flux = np.full(reference.size, np.nan)
    combined_uncertainty = np.full(reference.size, np.nan)
    n_combined = np.zeros(reference.size, dtype=int)
    n_rejected = np.zeros(reference.size, dtype=int)

    for j in range(reference.size):
        values = resampled_flux[:, j]
        kept = ~np.isnan(values)
        n_valid = int(np.count_nonzero(kept))
        if n_valid == 0:
            continue

        if sigma_clip is not None and n_valid >= 3:
            for _ in range(max_iters):
                median = np.median(values[kept])
                mad = float(np.median(np.abs(values[kept] - median)))
                sigma = max(mad * _MAD_TO_SIGMA, 1e-12)
                new_kept = kept & (np.abs(values - median) <= sigma_clip * sigma)
                if np.array_equal(new_kept, kept) or np.count_nonzero(new_kept) < 2:
                    break
                kept = new_kept

        n_used = int(np.count_nonzero(kept))
        n_combined[j] = n_used
        n_rejected[j] = n_valid - n_used
        if n_used == 0:
            continue

        if has_uncertainty and method == "mean":
            unc_values = resampled_unc[:, j][kept]
            variance = np.clip(unc_values**2, 1e-300, None)
            weights = 1.0 / variance
            combined_flux[j] = float(np.sum(values[kept] * weights) / np.sum(weights))
            combined_uncertainty[j] = float(math.sqrt(1.0 / np.sum(weights)))
        else:
            combined_flux[j] = float(np.median(values[kept])) if method == "median" else float(np.mean(values[kept]))
            if n_used >= 2:
                combined_uncertainty[j] = float(np.std(values[kept], ddof=1) / math.sqrt(n_used))

    return CombinedSpectrum(
        wavelength=reference,
        flux=combined_flux,
        flux_uncertainty=combined_uncertainty,
        n_combined=n_combined,
        n_rejected=n_rejected,
        method=method,
    )
