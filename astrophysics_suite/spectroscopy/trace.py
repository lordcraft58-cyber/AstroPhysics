"""Extracción de traza espectral -- equivalente propio de `apall` de
IRAF: localizar el rastro espacial de la fuente a lo largo del eje de
dispersión, y extraer un espectro 1D de la imagen 2D por suma simple o
por extracción óptima (Horne 1986, PASP 98, 609).

Convención fija: eje 0 (filas) = espacial, eje 1 (columnas) = dispersión
-- transponer antes de llamar si la imagen viene orientada al revés.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class TraceResult:
    columns: np.ndarray
    """Índices de columna (dispersión) cubiertos por la traza."""
    center_px: np.ndarray
    """Centro espacial (fila, subpíxel) ajustado en cada columna."""
    fit_degree: int
    rms_residual_px: float


def trace_spectrum(
    data: np.ndarray,
    *,
    initial_center_px: float,
    search_half_width: float = 8.0,
    fit_degree: int = 3,
    sigma_clip: float = 3.0,
    max_iters: int = 5,
) -> TraceResult:
    """Sigue el centroide ponderado por flujo columna a columna (una
    ventana de búsqueda alrededor de la posición de la columna anterior,
    para no perder la traza si el objeto se curva o se inclina), y ajusta
    un polinomio suave con rechazo iterativo de columnas ruidosas
    (rayos cósmicos, columnas sin señal) -- el resultado es el centro de
    extracción que usan `extract_sum`/`extract_optimal`.
    """
    if data.ndim != 2:
        raise ValueError("trace_spectrum opera sobre imágenes 2D (espacial x dispersión)")
    height, n_columns = data.shape
    if not (0 <= initial_center_px < height):
        raise ValueError("initial_center_px debe caer dentro de la imagen")

    centers = np.full(n_columns, np.nan)
    current_center = initial_center_px
    for col in range(n_columns):
        row_lo = max(0, int(round(current_center - search_half_width)))
        row_hi = min(height, int(round(current_center + search_half_width)) + 1)
        window = data[row_lo:row_hi, col]
        floor = np.percentile(window, 10)
        weights = np.clip(window - floor, a_min=0.0, a_max=None)
        total_weight = np.sum(weights)
        if total_weight <= 0:
            continue
        rows = np.arange(row_lo, row_hi)
        centroid = float(np.sum(rows * weights) / total_weight)
        centers[col] = centroid
        current_center = centroid

    valid = ~np.isnan(centers)
    if np.count_nonzero(valid) < fit_degree + 1:
        raise ValueError("no hay suficientes columnas con señal para ajustar la traza")

    columns_all = np.arange(n_columns)
    columns, values = columns_all[valid], centers[valid]

    for _ in range(max_iters):
        coeffs = np.polyfit(columns, values, deg=fit_degree)
        residuals = values - np.polyval(coeffs, columns)
        mad = float(np.median(np.abs(residuals)))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-6)
        keep = np.abs(residuals) <= sigma_clip * sigma
        if np.all(keep) or np.count_nonzero(keep) < fit_degree + 1:
            break
        columns, values = columns[keep], values[keep]

    coeffs = np.polyfit(columns, values, deg=fit_degree)
    fitted_all = np.polyval(coeffs, columns_all)
    rms = float(math.sqrt(np.mean((values - np.polyval(coeffs, columns)) ** 2)))

    return TraceResult(columns=columns_all, center_px=fitted_all, fit_degree=fit_degree, rms_residual_px=rms)


def _background_per_column(
    data: np.ndarray, trace: TraceResult, *, aperture_half_width: float, bg_offset: float, bg_half_width: float
) -> np.ndarray:
    height, n_columns = data.shape
    background = np.zeros(n_columns)
    for col in range(n_columns):
        center = trace.center_px[col]
        samples = []
        for sign in (-1, 1):
            lo = int(round(center + sign * bg_offset - bg_half_width))
            hi = int(round(center + sign * bg_offset + bg_half_width)) + 1
            lo, hi = max(0, lo), min(height, hi)
            if hi > lo:
                samples.append(data[lo:hi, col])
        background[col] = float(np.median(np.concatenate(samples))) if samples else 0.0
    return background


@dataclass(frozen=True)
class ExtractedSpectrum:
    flux: np.ndarray
    flux_uncertainty: np.ndarray
    background_per_pixel: np.ndarray
    method: str


def extract_sum(
    data: np.ndarray,
    uncertainty: np.ndarray,
    trace: TraceResult,
    *,
    aperture_half_width: float = 4.0,
    bg_offset: float = 10.0,
    bg_half_width: float = 4.0,
) -> ExtractedSpectrum:
    """Extracción por suma simple en una ventana espacial fija alrededor
    de la traza, con fondo local estimado a ambos lados (equivalente al
    modo `sum` de `apall`)."""
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    height, n_columns = data.shape
    background = _background_per_column(data, trace, aperture_half_width=aperture_half_width, bg_offset=bg_offset, bg_half_width=bg_half_width)

    flux = np.zeros(n_columns)
    flux_unc = np.zeros(n_columns)
    for col in range(n_columns):
        center = trace.center_px[col]
        lo = max(0, int(round(center - aperture_half_width)))
        hi = min(height, int(round(center + aperture_half_width)) + 1)
        n_pixels = hi - lo
        flux[col] = float(np.sum(data[lo:hi, col])) - background[col] * n_pixels
        flux_unc[col] = math.sqrt(float(np.sum(uncertainty[lo:hi, col] ** 2)))

    return ExtractedSpectrum(flux=flux, flux_uncertainty=flux_unc, background_per_pixel=background, method="sum")


def extract_optimal(
    data: np.ndarray,
    uncertainty: np.ndarray,
    trace: TraceResult,
    *,
    aperture_half_width: float = 4.0,
    bg_offset: float = 10.0,
    bg_half_width: float = 4.0,
) -> ExtractedSpectrum:
    """Extracción óptima (Horne 1986): construye un perfil espacial
    normalizado compartido -- la mediana, columna a columna, del perfil
    ya normalizado a suma 1 (robusta frente a rayos cósmicos residuales
    en columnas individuales) -- y pondera cada píxel por
    `perfil / varianza` en vez de darle a todos el mismo peso. Maximiza
    la S/N para una fuente débil frente a la extracción por suma simple,
    exactamente el resultado que motiva el método (Horne 1986, sección 2).
    """
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    height, n_columns = data.shape
    background = _background_per_column(data, trace, aperture_half_width=aperture_half_width, bg_offset=bg_offset, bg_half_width=bg_half_width)

    half = int(round(aperture_half_width))
    window_size = 2 * half + 1
    profiles = np.full((n_columns, window_size), np.nan)
    sum_flux_estimate = np.zeros(n_columns)

    for col in range(n_columns):
        center_row = int(round(trace.center_px[col]))
        lo, hi = center_row - half, center_row + half + 1
        if lo < 0 or hi > height:
            continue
        column_values = data[lo:hi, col] - background[col]
        total = np.sum(column_values)
        sum_flux_estimate[col] = total
        if total > 0:
            profiles[col] = np.clip(column_values / total, a_min=0.0, a_max=None)

    valid_columns = ~np.all(np.isnan(profiles), axis=1)
    master_profile = np.nanmedian(profiles[valid_columns], axis=0)
    master_profile = np.clip(master_profile, a_min=0.0, a_max=None)
    profile_sum = np.sum(master_profile)
    if profile_sum <= 0:
        raise ValueError("no se pudo construir un perfil espacial válido (sin señal en la traza)")
    master_profile = master_profile / profile_sum

    flux = np.zeros(n_columns)
    flux_unc = np.zeros(n_columns)
    for col in range(n_columns):
        center_row = int(round(trace.center_px[col]))
        lo, hi = center_row - half, center_row + half + 1
        if lo < 0 or hi > height:
            continue
        column_values = data[lo:hi, col] - background[col]
        variance = np.clip(uncertainty[lo:hi, col] ** 2, a_min=1e-12, a_max=None)
        weights = master_profile / variance
        denominator = float(np.sum(master_profile * weights))
        if denominator <= 0:
            continue
        flux[col] = float(np.sum(weights * column_values)) / denominator
        flux_unc[col] = math.sqrt(1.0 / denominator)

    return ExtractedSpectrum(flux=flux, flux_uncertainty=flux_unc, background_per_pixel=background, method="optimal")
