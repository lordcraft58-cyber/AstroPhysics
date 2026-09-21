"""Generadores sintéticos de lámpara de calibración (§33) -- SOLO para
pruebas automáticas. Producen una imagen 2D (o un espectro 1D) con
líneas de posición CONOCIDA a partir de `line_catalog.py`, para poder
comprobar que todo el motor de calibración (detección de picos, ajuste
polinómico, escritura/lectura de WCS) recupera lo que de verdad se puso
ahí -- la única forma honesta de validar "la calibración recupera las
líneas con el RMS correcto" sin depender de una lámpara física.

Todo lo que produce este módulo lleva `CalibrationSource.SYNTHETIC`
quien lo use después (`calibration_provenance.py`) -- nunca se presenta
como una observación real.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

from astrophysics_suite.spectroscopy.line_catalog import SpectralLine, arc_catalog


@dataclass(frozen=True)
class SyntheticLampSpectrum:
    pixel: np.ndarray
    flux: np.ndarray
    true_wavelength_at_pixel: np.ndarray
    """Longitud de onda REAL en cada píxel -- la verdad contra la que
    se compara cualquier calibración recuperada."""
    injected_lines: tuple[tuple[float, SpectralLine], ...]
    """`(pixel_real, línea_de_catálogo)` de cada línea inyectada -- lo
    que un ajuste perfecto debería recuperar exactamente."""


def generate_synthetic_lamp_spectrum(
    lamp_name: str,
    *,
    n_pixels: int = 1024,
    dispersion_angstrom_per_px: float = 1.4,
    wavelength_at_pixel0: float = 3800.0,
    line_fwhm_px: float = 2.5,
    peak_amplitude: float = 3000.0,
    background: float = 100.0,
    read_noise: float = 5.0,
    seed: int = 0,
) -> SyntheticLampSpectrum:
    """Espectro 1D sintético de la lámpara `lamp_name` (§33): cada línea
    real del catálogo que cae dentro del rango cubierto se inyecta como
    un perfil gaussiano en su posición de píxel exacta (derivada de la
    dispersión lineal dada, no de una calibración previa -- este
    generador ES la verdad de referencia), con ruido Poisson+lectura
    realista encima.
    """
    if n_pixels < 2:
        raise ValueError("n_pixels debe ser >= 2")
    catalog = arc_catalog(lamp_name)
    pixel = np.arange(n_pixels, dtype=np.float64)
    true_wavelength = wavelength_at_pixel0 + dispersion_angstrom_per_px * pixel

    flux = np.full(n_pixels, background, dtype=np.float64)
    sigma_px = line_fwhm_px / 2.354820045
    injected: list[tuple[float, SpectralLine]] = []
    wl_min, wl_max = true_wavelength.min(), true_wavelength.max()
    for line in catalog:
        if not (wl_min <= line.wavelength_air_angstrom <= wl_max):
            continue
        line_pixel = (line.wavelength_air_angstrom - wavelength_at_pixel0) / dispersion_angstrom_per_px
        flux += peak_amplitude * np.exp(-((pixel - line_pixel) ** 2) / (2 * sigma_px**2))
        injected.append((float(line_pixel), line))

    rng = np.random.default_rng(seed)
    poisson_noise = rng.normal(0.0, np.sqrt(np.clip(flux, 1e-6, None)))
    flux_noisy = flux + poisson_noise + rng.normal(0.0, read_noise, n_pixels)

    return SyntheticLampSpectrum(
        pixel=pixel, flux=flux_noisy, true_wavelength_at_pixel=true_wavelength,
        injected_lines=tuple(sorted(injected, key=lambda item: item[0])),
    )


@dataclass(frozen=True)
class SyntheticLampFrame2D:
    data: np.ndarray
    true_wavelength_at_pixel: np.ndarray
    """Verdad de referencia en el eje de dispersión, EN LA FILA CENTRAL
    (`trace_row_center`) -- con `curvature_px` distinto de cero, otras
    filas están desplazadas respecto a esta."""
    trace_row_center: float
    injected_lines: tuple[tuple[float, SpectralLine], ...]
    cosmic_ray_pixels: tuple[tuple[int, int], ...]
    """`(fila, columna)` de cada rayo cósmico inyectado -- para poder
    comprobar que la limpieza de rayos cósmicos los encuentra de
    verdad, no una posición distinta."""
    dead_pixels: tuple[tuple[int, int], ...]


def generate_synthetic_lamp_frame2d(
    lamp_name: str,
    *,
    shape: tuple[int, int] = (60, 1024),
    dispersion_angstrom_per_px: float = 1.4,
    wavelength_at_pixel0: float = 3800.0,
    line_fwhm_px: float = 2.5,
    trace_row_center: float | None = None,
    spatial_sigma_px: float = 3.0,
    curvature_px: float = 0.0,
    peak_amplitude: float = 3000.0,
    background: float = 100.0,
    read_noise: float = 5.0,
    n_cosmic_rays: int = 0,
    cosmic_ray_amplitude: float = 40000.0,
    n_dead_pixels: int = 0,
    seed: int = 0,
) -> SyntheticLampFrame2D:
    """Imagen 2D sintética de una lámpara de calibración (§33): las
    mismas líneas que `generate_synthetic_lamp_spectrum`, repartidas a
    lo largo de una traza real con perfil espacial gaussiano,
    `curvature_px` de curvatura (desplazamiento parabólico de la traza
    entre el borde y el centro del eje de dispersión -- ninguna traza
    real es perfectamente recta), y opcionalmente rayos cósmicos y
    píxeles muertos inyectados en posiciones conocidas, para poder
    comprobar que se detectan donde de verdad están.
    """
    height, width = shape
    trace_row_center = trace_row_center if trace_row_center is not None else height / 2.0
    if not (0.0 <= trace_row_center < height):
        raise ValueError("trace_row_center debe caer dentro de la imagen")

    spectrum = generate_synthetic_lamp_spectrum(
        lamp_name, n_pixels=width, dispersion_angstrom_per_px=dispersion_angstrom_per_px,
        wavelength_at_pixel0=wavelength_at_pixel0, line_fwhm_px=line_fwhm_px,
        peak_amplitude=peak_amplitude, background=0.0, read_noise=0.0, seed=seed,
    )
    columns = np.arange(width, dtype=np.float64)
    # curvatura parabólica, cero en el centro de la dispersión -- misma
    # convención que usan los tests de `trace.py`.
    trace_center_per_col = trace_row_center + curvature_px * ((columns / width) - 0.5) ** 2

    rows = np.arange(height, dtype=np.float64)[:, np.newaxis]
    spatial_profile = np.exp(-((rows - trace_center_per_col[np.newaxis, :]) ** 2) / (2 * spatial_sigma_px**2))
    data = background + spatial_profile * spectrum.flux[np.newaxis, :]

    rng = np.random.default_rng(seed)
    data = data + rng.normal(0.0, np.sqrt(np.clip(data, 1e-6, None))) + rng.normal(0.0, read_noise, shape)

    cosmic_ray_pixels: list[tuple[int, int]] = []
    for _ in range(n_cosmic_rays):
        r, c = int(rng.integers(0, height)), int(rng.integers(0, width))
        data[r, c] += cosmic_ray_amplitude
        cosmic_ray_pixels.append((r, c))

    dead_pixels: list[tuple[int, int]] = []
    for _ in range(n_dead_pixels):
        r, c = int(rng.integers(0, height)), int(rng.integers(0, width))
        data[r, c] = 0.0
        dead_pixels.append((r, c))

    return SyntheticLampFrame2D(
        data=data.astype(np.float64), true_wavelength_at_pixel=spectrum.true_wavelength_at_pixel,
        trace_row_center=trace_row_center, injected_lines=spectrum.injected_lines,
        cosmic_ray_pixels=tuple(cosmic_ray_pixels), dead_pixels=tuple(dead_pixels),
    )


def apply_gaussian_seeing(data: np.ndarray, *, sigma_px: float) -> np.ndarray:
    """Suaviza `data` con una PSF gaussiana isótropa -- para simular el
    seeing/desenfoque óptico real sobre una imagen sintética ya
    generada (§33: "PSF" en la lista de qué debe poder generar el
    módulo de pruebas)."""
    if sigma_px <= 0:
        return data
    return ndimage.gaussian_filter(data, sigma=sigma_px)
