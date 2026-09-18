"""Pruebas reales de `spectroscopy/combine.py`: combinación por media
ponderada (con propagación de error formal contra la fórmula cerrada de
varianza inversa) y por mediana con rechazo real de un valor atípico
inyectado (rayo cósmico simulado en una sola exposición)."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.combine import combine_spectra


def _flat_spectrum(level: float, n: int = 50, *, w0: float = 6000.0, dw: float = 1.0) -> tuple[np.ndarray, np.ndarray]:
    wavelength = w0 + dw * np.arange(n, dtype=np.float64)
    flux = np.full(n, level)
    return wavelength, flux


def test_combine_mean_with_uncertainties_matches_inverse_variance_formula():
    wavelength, flux_a = _flat_spectrum(100.0)
    _, flux_b = _flat_spectrum(104.0)
    unc_a = np.full_like(flux_a, 2.0)
    unc_b = np.full_like(flux_b, 4.0)

    result = combine_spectra(
        [wavelength, wavelength], [flux_a, flux_b], [unc_a, unc_b],
        method="mean", sigma_clip=None,
    )

    expected_flux = (100.0 / 2.0**2 + 104.0 / 4.0**2) / (1.0 / 2.0**2 + 1.0 / 4.0**2)
    expected_uncertainty = math.sqrt(1.0 / (1.0 / 2.0**2 + 1.0 / 4.0**2))
    assert result.flux == pytest.approx(expected_flux, rel=1e-9)
    assert np.all(result.flux_uncertainty == pytest.approx(expected_uncertainty, rel=1e-9))
    assert np.all(result.n_combined == 2)
    assert np.all(result.n_rejected == 0)


def test_combine_median_rejects_a_single_exposure_cosmic_ray_spike():
    rng = np.random.default_rng(7)
    true_level = 500.0
    n_spectra = 6
    wavelength, _ = _flat_spectrum(true_level)
    fluxes = [true_level + rng.normal(0, 3.0, wavelength.size) for _ in range(n_spectra)]

    spike_column = 25
    fluxes[2] = fluxes[2].copy()
    fluxes[2][spike_column] += 5000.0  # rayo cósmico real en una sola exposición

    result = combine_spectra([wavelength] * n_spectra, fluxes, method="median", sigma_clip=3.0)

    assert result.flux[spike_column] == pytest.approx(true_level, abs=15.0)
    assert result.n_rejected[spike_column] == 1
    assert result.n_combined[spike_column] == n_spectra - 1


def test_combine_without_sigma_clip_leaves_the_spike_in_a_mean_combination():
    true_level = 500.0
    n_spectra = 4
    wavelength, _ = _flat_spectrum(true_level, n=5)
    fluxes = [np.full(5, true_level) for _ in range(n_spectra)]
    fluxes[0] = fluxes[0].copy()
    fluxes[0][2] += 4000.0

    result = combine_spectra([wavelength] * n_spectra, fluxes, method="mean", sigma_clip=None)

    expected_polluted_mean = (true_level * (n_spectra - 1) + (true_level + 4000.0)) / n_spectra
    assert result.flux[2] == pytest.approx(expected_polluted_mean, rel=1e-9)
    assert result.n_rejected[2] == 0  # sin sigma_clip, nada se rechaza


def test_combine_never_extrapolates_beyond_each_spectrums_own_range():
    wavelength_a = np.linspace(6000.0, 6050.0, 26)
    wavelength_b = np.linspace(6030.0, 6080.0, 26)
    flux_a = np.full_like(wavelength_a, 100.0)
    flux_b = np.full_like(wavelength_b, 200.0)

    result = combine_spectra([wavelength_a, wavelength_b], [flux_a, flux_b], method="median", sigma_clip=None)

    only_a = result.wavelength < wavelength_b[0]
    only_overlap = (result.wavelength >= wavelength_b[0]) & (result.wavelength <= wavelength_a[-1])
    assert np.all(result.n_combined[only_a] == 1)
    assert np.all(result.flux[only_a] == pytest.approx(100.0))
    assert np.all(result.n_combined[only_overlap] == 2)


def test_combine_median_without_uncertainty_estimates_scatter_from_the_sample():
    rng = np.random.default_rng(11)
    true_level, true_sigma = 300.0, 5.0
    n_spectra = 8
    wavelength, _ = _flat_spectrum(true_level, n=10)
    fluxes = [true_level + rng.normal(0, true_sigma, wavelength.size) for _ in range(n_spectra)]

    result = combine_spectra([wavelength] * n_spectra, fluxes, method="median", sigma_clip=3.0)

    expected_uncertainty_scale = true_sigma / math.sqrt(n_spectra)
    assert np.all(result.flux_uncertainty > 0)
    assert np.median(result.flux_uncertainty) == pytest.approx(expected_uncertainty_scale, rel=0.6)


def test_combine_single_contributing_spectrum_point_leaves_uncertainty_as_nan_without_input_uncertainties():
    wavelength_a = np.linspace(6000.0, 6010.0, 11)
    wavelength_b = np.linspace(6020.0, 6030.0, 11)  # sin solape real con A
    flux_a = np.full_like(wavelength_a, 100.0)
    flux_b = np.full_like(wavelength_b, 200.0)

    result = combine_spectra([wavelength_a, wavelength_b], [flux_a, flux_b], reference_wavelength=wavelength_a, method="median")

    assert np.all(result.n_combined == 1)
    assert np.all(np.isnan(result.flux_uncertainty))


def test_combine_rejects_fewer_than_two_spectra():
    wavelength, flux = _flat_spectrum(100.0)
    with pytest.raises(ValueError):
        combine_spectra([wavelength], [flux])


def test_combine_rejects_non_monotonic_wavelength():
    wavelength = np.array([6000.0, 6002.0, 6001.0, 6003.0])
    flux = np.full(4, 100.0)
    with pytest.raises(ValueError):
        combine_spectra([wavelength, wavelength], [flux, flux])


def test_combine_rejects_mismatched_shapes():
    wavelength, flux = _flat_spectrum(100.0)
    bad_flux = flux[:-1]
    with pytest.raises(ValueError):
        combine_spectra([wavelength, wavelength], [flux, bad_flux])


def test_combine_rejects_invalid_method():
    wavelength, flux = _flat_spectrum(100.0)
    with pytest.raises(ValueError):
        combine_spectra([wavelength, wavelength], [flux, flux], method="sum")
