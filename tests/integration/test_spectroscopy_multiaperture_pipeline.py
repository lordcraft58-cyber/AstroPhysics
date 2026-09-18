"""Cadena completa real con dos objetos distintos en la misma imagen 2D
(misma rendija, dos posiciones espaciales reales): detección automática
de ambas aperturas, extracción de cada una por separado, calibración en
longitud de onda compartida y medición de una línea DISTINTA por objeto
-- confirma que `extract_multi_aperture` separa los dos objetos
correctamente y que cada espectro extraído mide su propia línea real sin
mezclarse con la del otro objeto."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.lines import measure_line
from astrophysics_suite.spectroscopy.multiaperture import extract_multi_aperture
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

_DISPERSION_A_PER_PX = 2.0
_WAVELENGTH_AT_PX0 = 6000.0

_OBJECT_A_CENTER_ROW = 15.0
_OBJECT_B_CENTER_ROW = 45.0
_OBJECT_A_LINE_PIXEL = 80.0
_OBJECT_B_LINE_PIXEL = 160.0
_LINE_SIGMA_PX = 2.0


def _two_object_spectral_frame(shape=(60, 240), seed=9):
    rng = np.random.default_rng(seed)
    height, width = shape
    columns = np.arange(width, dtype=np.float64)
    rows = np.arange(height)[:, np.newaxis]

    data = np.full(shape, 50.0)
    for center_row, line_pixel in ((_OBJECT_A_CENTER_ROW, _OBJECT_A_LINE_PIXEL), (_OBJECT_B_CENTER_ROW, _OBJECT_B_LINE_PIXEL)):
        profile = np.exp(-((rows - center_row) ** 2) / (2 * 2.0**2))
        profile /= profile.sum(axis=0, keepdims=True)
        flux_per_column = 1500.0 + 5000.0 * np.exp(-((columns - line_pixel) ** 2) / (2 * _LINE_SIGMA_PX**2))
        data = data + flux_per_column[np.newaxis, :] * profile

    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data.astype(np.float64), uncertainty.astype(np.float64)


def test_multi_aperture_separates_two_real_objects_and_measures_each_ones_own_line():
    data, uncertainty = _two_object_spectral_frame()

    result = extract_multi_aperture(data, uncertainty, optimal_extraction=False, aperture_half_width=8.0, bg_offset=15.0, bg_half_width=4.0)

    assert result.failures == []
    assert len(result.apertures) == 2
    assert result.apertures[0].initial_center_px == pytest.approx(_OBJECT_A_CENTER_ROW, abs=1.5)
    assert result.apertures[1].initial_center_px == pytest.approx(_OBJECT_B_CENTER_ROW, abs=1.5)

    pixels = np.arange(data.shape[1], dtype=np.float64)
    reference_pixels = [0.0, 60.0, 120.0, 180.0, 239.0]
    reference_wavelengths = [_WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * p for p in reference_pixels]
    solution = fit_wavelength_solution(reference_pixels, reference_wavelengths, degree=1)
    wavelength = solution.pixel_to_wavelength(pixels)

    line_sigma_wavelength = _DISPERSION_A_PER_PX * _LINE_SIGMA_PX
    expected_centers = {
        result.apertures[0].aperture_id: _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * _OBJECT_A_LINE_PIXEL,
        result.apertures[1].aperture_id: _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * _OBJECT_B_LINE_PIXEL,
    }
    other_object_line = {
        result.apertures[0].aperture_id: _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * _OBJECT_B_LINE_PIXEL,
        result.apertures[1].aperture_id: _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * _OBJECT_A_LINE_PIXEL,
    }

    for aperture in result.apertures:
        continuum_fit = fit_continuum(wavelength, aperture.spectrum.flux, degree=1, sigma_clip=3.0, reject="both")

        own_line = measure_line(
            wavelength, aperture.spectrum.flux, continuum_fit.continuum,
            expected_wavelength=expected_centers[aperture.aperture_id], window_halfwidth=8 * line_sigma_wavelength,
        )
        assert own_line is not None
        assert own_line.center_wavelength == pytest.approx(expected_centers[aperture.aperture_id], abs=2.0)
        assert own_line.integrated_flux > 500.0  # línea real, claramente por encima del ruido

        # la línea del OTRO objeto no debe aparecer con fuerza comparable
        # en esta apertura -- confirma que las dos trazas no se mezclaron.
        cross_talk = measure_line(
            wavelength, aperture.spectrum.flux, continuum_fit.continuum,
            expected_wavelength=other_object_line[aperture.aperture_id], window_halfwidth=8 * line_sigma_wavelength,
        )
        if cross_talk is not None:
            assert cross_talk.integrated_flux < own_line.integrated_flux * 0.3
