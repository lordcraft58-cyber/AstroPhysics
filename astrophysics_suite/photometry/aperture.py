"""Fotometría de apertura -- equivalente propio de `noao.digiphot.apphot`
de IRAF: apertura circular con cobertura subpíxel, estimación de fondo
local por anillo de cielo con sigma-clipping robusto, y curva de
crecimiento (múltiples radios en una sola llamada, compartiendo el mismo
cielo local -- igual que hacía `phot` de IRAF).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


def aperture_coverage_mask(
    shape: tuple[int, int], x0: float, y0: float, radius: float, *, oversample: int = 8
) -> np.ndarray:
    """Fracción de cada píxel (0..1) cubierta por un círculo de radio
    `radius` centrado en `(x0, y0)` (convención de centro de píxel: el
    píxel entero `i` ocupa `[i-0.5, i+0.5)`).

    Los píxeles completamente dentro o completamente fuera se resuelven
    de forma analítica exacta; solo los píxeles de borde (donde el
    círculo realmente los atraviesa) se resuelven por submuestreo, así
    que el coste computacional escala con el perímetro, no con el área.
    """
    if radius <= 0:
        raise ValueError("radius debe ser positivo")
    height, width = shape
    half_diag = math.sqrt(2) / 2.0

    x_min = max(0, int(math.floor(x0 - radius - 1)))
    x_max = min(width, int(math.ceil(x0 + radius + 1)))
    y_min = max(0, int(math.floor(y0 - radius - 1)))
    y_max = min(height, int(math.ceil(y0 + radius + 1)))

    coverage = np.zeros(shape, dtype=np.float64)
    if x_min >= x_max or y_min >= y_max:
        return coverage

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    dist = np.sqrt((xx - x0) ** 2 + (yy - y0) ** 2)

    fully_inside = dist <= (radius - half_diag)
    fully_outside = dist >= (radius + half_diag)
    boundary = ~(fully_inside | fully_outside)

    local = np.zeros(xx.shape, dtype=np.float64)
    local[fully_inside] = 1.0

    if np.any(boundary):
        offsets = (np.arange(oversample) + 0.5) / oversample - 0.5
        sub_dy, sub_dx = np.meshgrid(offsets, offsets, indexing="ij")
        boundary_y, boundary_x = np.nonzero(boundary)
        for by, bx in zip(boundary_y, boundary_x):
            px, py = xx[by, bx], yy[by, bx]
            sub_dist = np.sqrt((px + sub_dx - x0) ** 2 + (py + sub_dy - y0) ** 2)
            local[by, bx] = float(np.mean(sub_dist <= radius))

    coverage[y_min:y_max, x_min:x_max] = local
    return coverage


@dataclass(frozen=True)
class SkyEstimate:
    median: float
    sigma_per_pixel: float
    n_pixels: int


def estimate_local_sky(
    data: np.ndarray,
    x0: float,
    y0: float,
    r_in: float,
    r_out: float,
    *,
    sigma_clip: float = 3.0,
    max_iters: int = 5,
) -> SkyEstimate:
    """Cielo local por anillo -- selección de píxeles por centro (no
    fraccional: la estimación de fondo no necesita precisión subpíxel, a
    diferencia de la suma de apertura) con rechazo iterativo robusto
    (MAD) de fuentes contaminantes dentro del anillo."""
    if not (0 < r_in < r_out):
        raise ValueError("se requiere 0 < r_in < r_out")
    height, width = data.shape
    y_min = max(0, int(math.floor(y0 - r_out)))
    y_max = min(height, int(math.ceil(y0 + r_out)) + 1)
    x_min = max(0, int(math.floor(x0 - r_out)))
    x_max = min(width, int(math.ceil(x0 + r_out)) + 1)
    if y_min >= y_max or x_min >= x_max:
        return SkyEstimate(median=0.0, sigma_per_pixel=0.0, n_pixels=0)

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    dist = np.sqrt((xx - x0) ** 2 + (yy - y0) ** 2)
    annulus = (dist >= r_in) & (dist < r_out)
    values = data[y_min:y_max, x_min:x_max][annulus]

    if values.size == 0:
        return SkyEstimate(median=0.0, sigma_per_pixel=0.0, n_pixels=0)

    for _ in range(max_iters):
        median = float(np.median(values))
        mad = float(np.median(np.abs(values - median)))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-9)
        keep = np.abs(values - median) <= sigma_clip * sigma
        if np.all(keep) or not np.any(keep):
            break
        values = values[keep]

    median = float(np.median(values))
    mad = float(np.median(np.abs(values - median)))
    sigma = mad * _MAD_TO_SIGMA
    return SkyEstimate(median=median, sigma_per_pixel=sigma, n_pixels=int(values.size))


@dataclass(frozen=True)
class ApertureMeasurement:
    radius_px: float
    n_pixels: float
    """Suma de coberturas fraccionales -- el "número efectivo de
    píxeles" de la apertura, no necesariamente entero."""
    raw_sum: float
    sky_per_pixel: float
    sky_sigma_per_pixel: float
    net_flux: float
    net_flux_uncertainty: float
    magnitude: float | None
    magnitude_uncertainty: float | None
    snr: float | None


def _magnitude_from_flux(flux: float, flux_uncertainty: float, zeropoint_mag: float) -> tuple[float | None, float | None]:
    if flux <= 0:
        return None, None
    magnitude = zeropoint_mag - 2.5 * math.log10(flux)
    # dm = 2.5/ln(10) * (sigma_f/f) -- propagación estándar mag<->flujo
    magnitude_uncertainty = (2.5 / math.log(10.0)) * (flux_uncertainty / flux) if flux_uncertainty > 0 else 0.0
    return magnitude, magnitude_uncertainty


def aperture_photometry(
    data: np.ndarray,
    uncertainty: np.ndarray,
    x0: float,
    y0: float,
    radii: list[float],
    *,
    sky_r_in: float,
    sky_r_out: float,
    zeropoint_mag: float = 25.0,
    oversample: int = 8,
    sky_sigma_clip: float = 3.0,
) -> list[ApertureMeasurement]:
    """Fotometría de apertura múltiple (curva de crecimiento) compartiendo
    un único cielo local estimado una vez por anillo -- igual que `phot`
    de IRAF cuando se le da una lista de radios en una sola pasada."""
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    if not radii:
        raise ValueError("radii no puede estar vacío")

    sky = estimate_local_sky(data, x0, y0, sky_r_in, sky_r_out, sigma_clip=sky_sigma_clip)

    measurements: list[ApertureMeasurement] = []
    for radius in radii:
        coverage = aperture_coverage_mask(data.shape, x0, y0, radius, oversample=oversample)
        n_pixels = float(np.sum(coverage))
        raw_sum = float(np.sum(data * coverage))
        sky_total = sky.median * n_pixels
        net_flux = raw_sum - sky_total

        # varianza: ruido de apertura propagado (ponderado por cobertura) +
        # incertidumbre del propio nivel de cielo local propagada sobre
        # `n_pixels` píxeles de apertura (el mismo cielo se resta de todos).
        aperture_variance = float(np.sum((uncertainty * coverage) ** 2))
        sky_level_uncertainty = sky.sigma_per_pixel / math.sqrt(max(sky.n_pixels, 1))
        sky_variance = (sky_level_uncertainty * n_pixels) ** 2
        net_flux_uncertainty = math.sqrt(aperture_variance + sky_variance)

        magnitude, magnitude_uncertainty = _magnitude_from_flux(net_flux, net_flux_uncertainty, zeropoint_mag)
        snr = net_flux / net_flux_uncertainty if net_flux_uncertainty > 0 else None

        measurements.append(
            ApertureMeasurement(
                radius_px=radius,
                n_pixels=n_pixels,
                raw_sum=raw_sum,
                sky_per_pixel=sky.median,
                sky_sigma_per_pixel=sky.sigma_per_pixel,
                net_flux=net_flux,
                net_flux_uncertainty=net_flux_uncertainty,
                magnitude=magnitude,
                magnitude_uncertainty=magnitude_uncertainty,
                snr=snr,
            )
        )
    return measurements


@dataclass(frozen=True)
class GrowthCurveFit:
    """Ajuste de la curva de crecimiento (flujo neto acumulado en función
    del radio de apertura) a un modelo de saturación monótono, más el
    radio de apertura recomendado -- el que maximiza la señal/ruido
    realmente medida entre los radios probados, criterio estándar de
    "apertura óptima" de una curva de crecimiento (p. ej. Howell,
    *Handbook of CCD Astronomy*, cap. 5), no un radio fijo elegido a
    ciegas."""

    radii_px: tuple[float, ...]
    net_fluxes: tuple[float, ...]
    asymptotic_flux: float
    scale_radius_px: float
    shape_index: float
    rms_residual: float
    optimal_radius_px: float
    optimal_snr: float
    flux_fraction_at_optimal: float


def _growth_curve_model(radius: np.ndarray, asymptotic_flux: float, scale_radius: float, shape_index: float) -> np.ndarray:
    return asymptotic_flux * (1.0 - np.exp(-((radius / scale_radius) ** shape_index)))


def fit_curve_of_growth(measurements: list[ApertureMeasurement]) -> GrowthCurveFit:
    """Ajusta la curva de crecimiento real -- flujo neto ya medido por
    `aperture_photometry` en varios radios de la misma fuente -- a un
    modelo de saturación monótono `F(r) = F_inf * (1 - exp(-(r/r0)^p))`,
    y recomienda como radio óptimo el que maximiza la señal/ruido medida
    (no extrapolada) entre los radios realmente probados."""
    from scipy.optimize import curve_fit

    if len(measurements) < 4:
        raise ValueError("se necesitan al menos 4 radios distintos para ajustar una curva de crecimiento")

    radii = np.array([m.radius_px for m in measurements], dtype=np.float64)
    fluxes = np.array([m.net_flux for m in measurements], dtype=np.float64)
    if len(set(radii.tolist())) != len(radii):
        raise ValueError("los radios de las medidas deben ser distintos entre sí")

    order = np.argsort(radii)
    radii, fluxes = radii[order], fluxes[order]

    initial_guess = (max(float(np.max(fluxes)), 1.0) * 1.2, float(np.median(radii)), 2.0)
    bounds = ([1e-9, 1e-9, 0.1], [np.inf, np.inf, 20.0])
    try:
        popt, _ = curve_fit(_growth_curve_model, radii, fluxes, p0=initial_guess, bounds=bounds, maxfev=10000)
    except RuntimeError as exc:
        raise ValueError(f"el ajuste de la curva de crecimiento no convergió: {exc}") from exc

    asymptotic_flux, scale_radius, shape_index = (float(v) for v in popt)
    residuals = fluxes - _growth_curve_model(radii, *popt)
    rms_residual = float(np.sqrt(np.mean(residuals**2)))

    valid = [(m.radius_px, m.snr, m.net_flux) for m in measurements if m.snr is not None]
    if not valid:
        raise ValueError("ninguna medida tiene señal/ruido válida -- no se puede recomendar un radio óptimo")
    optimal_radius_px, optimal_snr, optimal_flux = max(valid, key=lambda row: row[1])
    flux_fraction_at_optimal = optimal_flux / asymptotic_flux if asymptotic_flux > 0 else 0.0

    return GrowthCurveFit(
        radii_px=tuple(radii.tolist()),
        net_fluxes=tuple(fluxes.tolist()),
        asymptotic_flux=asymptotic_flux,
        scale_radius_px=scale_radius,
        shape_index=shape_index,
        rms_residual=rms_residual,
        optimal_radius_px=float(optimal_radius_px),
        optimal_snr=float(optimal_snr),
        flux_fraction_at_optimal=float(flux_fraction_at_optimal),
    )
