"""Cadena completa de espectroscopía con varias exposiciones reales:
tres imágenes 2D sintéticas independientes del mismo objeto (mismo
continuo y línea reales, tres realizaciones de ruido distintas) se
trazan y extraen por separado, se calibran en longitud de onda, se
combinan con `combine_spectra` y se mide la línea sobre el resultado --
demuestra la mejora real de señal/ruido que es la razón de ser de este
motor, no solo que `combine_spectra` "no lanza excepción"."""
from __future__ import annotations

import numpy as np

from astrophysics_suite.spectroscopy.combine import combine_spectra
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.lines import measure_line
from astrophysics_suite.spectroscopy.trace import extract_sum, trace_spectrum
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

_DISPERSION_A_PER_PX = 2.0
_WAVELENGTH_AT_PX0 = 6000.0
_LINE_PIXEL = 120.0
_LINE_SIGMA_PX = 2.0


def _synthetic_2d_spectrum_with_emission_line(seed: int, shape=(41, 240)):
    rng = np.random.default_rng(seed)
    height, width = shape
    columns = np.arange(width, dtype=np.float64)
    rows = np.arange(height)[:, np.newaxis]

    profile = np.exp(-((rows - 20.0) ** 2) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)

    flux_per_column = 2000.0 + 6000.0 * np.exp(-((columns - _LINE_PIXEL) ** 2) / (2 * _LINE_SIGMA_PX**2))
    data = 50.0 + flux_per_column[np.newaxis, :] * profile
    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data.astype(np.float64), uncertainty.astype(np.float64)


def _extract_calibrated_spectrum(seed: int):
    data, uncertainty = _synthetic_2d_spectrum_with_emission_line(seed)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    extracted = extract_sum(data, uncertainty, trace, aperture_half_width=10.0, bg_offset=15.0, bg_half_width=4.0)

    pixels = np.arange(data.shape[1], dtype=np.float64)
    reference_pixels = [0.0, 60.0, 120.0, 180.0, 239.0]
    reference_wavelengths = [_WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * p for p in reference_pixels]
    solution = fit_wavelength_solution(reference_pixels, reference_wavelengths, degree=1)
    wavelength = solution.pixel_to_wavelength(pixels)
    return wavelength, extracted.flux, extracted.flux_uncertainty


def _measure_line_relative_uncertainty(wavelength, flux, flux_uncertainty):
    continuum_fit = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, reject="both")
    line_center_wavelength = _WAVELENGTH_AT_PX0 + _DISPERSION_A_PER_PX * _LINE_PIXEL
    line_sigma_wavelength = _DISPERSION_A_PER_PX * _LINE_SIGMA_PX
    result = measure_line(
        wavelength, flux, continuum_fit.continuum,
        expected_wavelength=line_center_wavelength, window_halfwidth=8 * line_sigma_wavelength,
        flux_uncertainty=flux_uncertainty,
    )
    assert result is not None
    assert result.integrated_flux_error is not None and result.integrated_flux_error > 0
    return abs(result.integrated_flux_error / result.integrated_flux)


def test_combining_three_exposures_improves_line_measurement_snr_over_a_single_exposure():
    exposures = [_extract_calibrated_spectrum(seed) for seed in (101, 202, 303)]

    single_wavelength, single_flux, single_unc = exposures[0]
    single_relative_error = _measure_line_relative_uncertainty(single_wavelength, single_flux, single_unc)

    # sin sigma_clip aquí a propósito: el rechazo de atípicos ya tiene su
    # propia prueba dedicada (test_combine.py) -- esta prueba aísla
    # específicamente la mejora de señal/ruido al combinar, sin mezclar
    # el ruido estadístico real de rechazar con muestras de tamaño 3.
    combined = combine_spectra(
        [w for w, _, _ in exposures], [f for _, f, _ in exposures], [u for _, _, u in exposures],
        method="mean", sigma_clip=None,
    )
    assert not np.any(np.isnan(combined.flux))
    assert np.all(combined.n_combined == 3)

    combined_relative_error = _measure_line_relative_uncertainty(combined.wavelength, combined.flux, combined.flux_uncertainty)

    # tres exposiciones independientes deberían mejorar la S/N en un
    # factor cercano a sqrt(3) =~ 1.73 -- tolerancia amplia porque es
    # ruido real, no una identidad exacta, pero la mejora tiene que ser
    # real y sustancial, no marginal.
    assert combined_relative_error < single_relative_error / 1.3
