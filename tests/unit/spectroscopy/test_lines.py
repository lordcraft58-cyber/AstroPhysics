"""Pruebas reales de `spectroscopy/lines.py` contra una línea gaussiana
sintética con parámetros analíticos conocidos (amplitud, sigma,
continuo) -- las magnitudes medidas (flujo integrado, EW, FWHM) se
comparan contra la fórmula cerrada, no solo contra "no lanza excepción"."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.lines import measure_line

_SQRT_2PI = math.sqrt(2.0 * math.pi)
_FWHM_FACTOR = 2.0 * math.sqrt(2.0 * math.log(2.0))


def _gaussian_line(*, amplitude: float, center: float, sigma: float, continuum_level: float, n=2001, span_sigma=8.0):
    wavelength = np.linspace(center - span_sigma * sigma, center + span_sigma * sigma, n)
    continuum = np.full_like(wavelength, continuum_level)
    flux = continuum + amplitude * np.exp(-((wavelength - center) ** 2) / (2 * sigma**2))
    return wavelength, flux, continuum


def test_measure_line_emission_matches_analytic_gaussian_integral():
    amplitude, sigma, continuum_level, center = 400.0, 3.0, 100.0, 6563.0
    wavelength, flux, continuum = _gaussian_line(amplitude=amplitude, center=center, sigma=sigma, continuum_level=continuum_level)

    result = measure_line(wavelength, flux, continuum, expected_wavelength=center, window_halfwidth=8 * sigma)

    assert result is not None
    expected_integrated_flux = amplitude * sigma * _SQRT_2PI
    assert result.integrated_flux == pytest.approx(expected_integrated_flux, rel=1e-3)
    assert result.equivalent_width == pytest.approx(-expected_integrated_flux / continuum_level, rel=1e-3)
    assert result.fwhm == pytest.approx(_FWHM_FACTOR * sigma, rel=2e-2)
    assert result.center_wavelength == pytest.approx(center, abs=1e-6)


def test_measure_line_absorption_matches_analytic_gaussian_integral():
    amplitude, sigma, continuum_level, center = -40.0, 2.5, 100.0, 4861.0
    wavelength, flux, continuum = _gaussian_line(amplitude=amplitude, center=center, sigma=sigma, continuum_level=continuum_level)

    result = measure_line(wavelength, flux, continuum, expected_wavelength=center, window_halfwidth=8 * sigma)

    assert result is not None
    expected_integrated_flux = amplitude * sigma * _SQRT_2PI  # negativo: absorción
    assert result.integrated_flux == pytest.approx(expected_integrated_flux, rel=1e-3)
    assert result.integrated_flux < 0
    assert result.equivalent_width > 0  # convención splot: positivo para absorción
    assert result.equivalent_width == pytest.approx(-expected_integrated_flux / continuum_level, rel=1e-3)
    assert result.fwhm == pytest.approx(_FWHM_FACTOR * sigma, rel=2e-2)


def test_measure_line_returns_none_when_window_falls_outside_the_spectrum():
    wavelength, flux, continuum = _gaussian_line(amplitude=200.0, center=6563.0, sigma=2.0, continuum_level=100.0)
    result = measure_line(wavelength, flux, continuum, expected_wavelength=9000.0, window_halfwidth=5.0)
    assert result is None


def test_measure_line_returns_none_with_fewer_than_three_points_in_window():
    wavelength = np.array([6560.0, 6563.0, 6566.0, 6600.0])
    flux = np.array([100.0, 500.0, 100.0, 100.0])
    continuum = np.full_like(wavelength, 100.0)
    result = measure_line(wavelength, flux, continuum, expected_wavelength=6563.0, window_halfwidth=1.0)
    assert result is None


def test_measure_line_fwhm_is_none_when_window_too_narrow_to_reach_half_max():
    amplitude, sigma, continuum_level, center = 400.0, 3.0, 100.0, 6563.0
    wavelength, flux, continuum = _gaussian_line(amplitude=amplitude, center=center, sigma=sigma, continuum_level=continuum_level, span_sigma=8.0)

    # Ventana mucho más estrecha que el HWHM real (~1.18*sigma): el
    # perfil dentro de la ventana nunca cae a la mitad del pico.
    result = measure_line(wavelength, flux, continuum, expected_wavelength=center, window_halfwidth=0.3 * sigma)

    assert result is not None
    assert result.fwhm is None


def test_measure_line_equivalent_width_is_none_with_nonpositive_continuum():
    wavelength = np.linspace(6553.0, 6573.0, 41)
    continuum = np.full_like(wavelength, 100.0)
    continuum[20] = 0.0  # un punto degenerado dentro de la ventana
    flux = continuum + 50.0 * np.exp(-((wavelength - 6563.0) ** 2) / (2 * 2.0**2))

    result = measure_line(wavelength, flux, continuum, expected_wavelength=6563.0, window_halfwidth=10.0)

    assert result is not None
    assert result.equivalent_width is None
    assert result.equivalent_width_error is None
    assert result.integrated_flux != 0.0  # el flujo integrado sigue siendo calculable


def test_measure_line_propagates_real_flux_uncertainty():
    amplitude, sigma, continuum_level, center = 400.0, 3.0, 100.0, 6563.0
    wavelength, flux, continuum = _gaussian_line(amplitude=amplitude, center=center, sigma=sigma, continuum_level=continuum_level)
    flux_uncertainty = np.full_like(wavelength, 2.0)

    result = measure_line(
        wavelength, flux, continuum, expected_wavelength=center, window_halfwidth=8 * sigma, flux_uncertainty=flux_uncertainty,
    )

    assert result is not None
    assert result.integrated_flux_error is not None
    assert result.integrated_flux_error > 0.0
    assert result.equivalent_width_error is not None
    assert result.equivalent_width_error > 0.0


def test_measure_line_without_flux_uncertainty_leaves_errors_none():
    wavelength, flux, continuum = _gaussian_line(amplitude=200.0, center=6563.0, sigma=2.0, continuum_level=100.0)
    result = measure_line(wavelength, flux, continuum, expected_wavelength=6563.0, window_halfwidth=10.0)
    assert result is not None
    assert result.integrated_flux_error is None
    assert result.equivalent_width_error is None


def test_measure_line_rejects_mismatched_shapes():
    wavelength = np.linspace(6553.0, 6573.0, 41)
    flux = np.zeros(41)
    continuum = np.zeros(40)
    with pytest.raises(ValueError):
        measure_line(wavelength, flux, continuum, expected_wavelength=6563.0, window_halfwidth=5.0)


def test_measure_line_rejects_nonpositive_window_halfwidth():
    wavelength, flux, continuum = _gaussian_line(amplitude=200.0, center=6563.0, sigma=2.0, continuum_level=100.0)
    with pytest.raises(ValueError):
        measure_line(wavelength, flux, continuum, expected_wavelength=6563.0, window_halfwidth=0.0)
