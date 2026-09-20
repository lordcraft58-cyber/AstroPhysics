"""Cadena completa de espectroscopía sobre una imagen 2D sintética real:
`trace_spectrum` -> `extract_sum` -> `fit_wavelength_solution` ->
`fit_continuum` -> `measure_line`, encadenando los motores reales tal
como los usaría un flujo real de la GUI -- no una llamada aislada a
`measure_line` con arrays fabricados a mano."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.lines import measure_line
from astrophysics_suite.spectroscopy.trace import SkyWindow, extract_sum, trace_spectrum
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

_DISPERSION_A_PER_PX = 2.0
_WAVELENGTH_AT_PX0 = 6000.0
_SQRT_2PI = math.sqrt(2.0 * math.pi)
_FWHM_FACTOR = 2.0 * math.sqrt(2.0 * math.log(2.0))


def _synthetic_2d_spectrum_with_emission_line(
    shape=(41, 240), *, center_row=20.0, spatial_sigma=2.0, continuum_flux=2000.0,
    line_pixel=120.0, line_sigma_px=2.0, line_amplitude=6000.0, background=50.0, seed=3,
):
    rng = np.random.default_rng(seed)
    height, width = shape
    columns = np.arange(width, dtype=np.float64)
    rows = np.arange(height)[:, np.newaxis]

    profile = np.exp(-((rows - center_row) ** 2) / (2 * spatial_sigma**2))
    profile /= profile.sum(axis=0, keepdims=True)

    # Flujo total real por columna: continuo suave + una línea de
    # emisión gaussiana real centrada en `line_pixel` -- el mismo tipo
    # de perfil que una línea real en un espectro extraído.
    flux_per_column = continuum_flux + line_amplitude * np.exp(-((columns - line_pixel) ** 2) / (2 * line_sigma_px**2))

    data = background + flux_per_column[np.newaxis, :] * profile
    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data.astype(np.float64), uncertainty.astype(np.float64)


def test_full_chain_recovers_a_real_emission_line_from_a_synthetic_2d_spectrum():
    data, uncertainty = _synthetic_2d_spectrum_with_emission_line()

    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    extracted = extract_sum(
        data, uncertainty, trace, aperture_half_width=10.0,
        sky_windows=(SkyWindow(offset_px=-15.0, half_width_px=4.0), SkyWindow(offset_px=15.0, half_width_px=4.0)),
    )

    pixels = np.arange(data.shape[1], dtype=np.float64)
    # Puntos de referencia reales (píxel, longitud de onda) de una
    # dispersión lineal conocida -- mismo contrato que recibiría
    # `fit_wavelength_solution` tras identificar líneas de arco reales.
    reference_pixels = [0.0, 60.0, 120.0, 180.0, 239.0]
    reference_wavelengths = [_WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * p for p in reference_pixels]
    solution = fit_wavelength_solution(reference_pixels, reference_wavelengths, degree=1)
    assert solution.rms_residual == pytest.approx(0.0, abs=1e-6)

    wavelength = solution.pixel_to_wavelength(pixels)
    continuum_fit = fit_continuum(wavelength, extracted.flux, degree=1, sigma_clip=3.0, reject="both")

    line_center_wavelength = _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * 120.0
    line_sigma_wavelength = _DISPERSION_A_PER_PX * 2.0
    result = measure_line(
        wavelength, extracted.flux, continuum_fit.continuum,
        expected_wavelength=line_center_wavelength, window_halfwidth=8 * line_sigma_wavelength,
        flux_uncertainty=extracted.flux_uncertainty,
    )

    assert result is not None
    assert result.center_wavelength == pytest.approx(line_center_wavelength, abs=2.0)

    expected_integrated_flux = 6000.0 * (line_sigma_wavelength) * _SQRT_2PI
    assert result.integrated_flux == pytest.approx(expected_integrated_flux, rel=0.1)
    assert result.fwhm == pytest.approx(_FWHM_FACTOR * line_sigma_wavelength, rel=0.15)
    assert result.equivalent_width is not None
    assert result.equivalent_width < 0  # emisión real, convención splot
    assert result.integrated_flux_error is not None and result.integrated_flux_error > 0
