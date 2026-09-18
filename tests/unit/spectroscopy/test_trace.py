from __future__ import annotations


import numpy as np
import pytest

from astrophysics_suite.spectroscopy.trace import extract_optimal, extract_sum, trace_spectrum


def _synthetic_2d_spectrum(shape=(41, 200), *, center=20.0, sigma=2.0, flux_per_col=2000.0, background=50.0, curve=0.0, seed=1):
    rng = np.random.default_rng(seed)
    height, width = shape
    columns = np.arange(width)
    true_center = center + curve * (columns / width) ** 2
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - true_center[np.newaxis, :]) ** 2) / (2 * sigma**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = background + flux_per_col * profile
    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data, uncertainty, true_center


def test_trace_spectrum_recovers_known_straight_trace():
    data, _, true_center = _synthetic_2d_spectrum(curve=0.0)
    result = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    np.testing.assert_allclose(result.center_px, true_center, atol=0.5)


def test_trace_spectrum_follows_curved_trace():
    data, _, true_center = _synthetic_2d_spectrum(curve=6.0)
    result = trace_spectrum(data, initial_center_px=20.0, fit_degree=3)
    np.testing.assert_allclose(result.center_px, true_center, atol=0.7)


def test_trace_spectrum_rejects_non_2d_input():
    with pytest.raises(ValueError):
        trace_spectrum(np.zeros((5, 5, 5)), initial_center_px=2.0)


def test_trace_spectrum_rejects_center_outside_image():
    with pytest.raises(ValueError):
        trace_spectrum(np.zeros((10, 10)), initial_center_px=50.0)


def test_extract_sum_recovers_known_flux():
    flux_per_col = 3000.0
    data, uncertainty, true_center = _synthetic_2d_spectrum(flux_per_col=flux_per_col, curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)

    result = extract_sum(data, uncertainty, trace, aperture_half_width=8.0, bg_offset=14.0, bg_half_width=4.0)
    median_flux = float(np.median(result.flux))
    assert median_flux == pytest.approx(flux_per_col, rel=0.05)


def test_extract_optimal_achieves_higher_snr_than_sum_for_faint_source():
    """El resultado central de Horne 1986: para una fuente débil, la
    extracción óptima da mayor S/N que la suma simple sobre la misma
    ventana de apertura."""
    data, uncertainty, _ = _synthetic_2d_spectrum(flux_per_col=150.0, background=200.0, seed=3)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)

    sum_result = extract_sum(data, uncertainty, trace, aperture_half_width=8.0, bg_offset=14.0, bg_half_width=4.0)
    optimal_result = extract_optimal(data, uncertainty, trace, aperture_half_width=8.0, bg_offset=14.0, bg_half_width=4.0)

    sum_snr = np.median(sum_result.flux / sum_result.flux_uncertainty)
    optimal_snr = np.median(optimal_result.flux / optimal_result.flux_uncertainty)
    assert optimal_snr > sum_snr


def test_extract_optimal_rejects_shape_mismatch():
    data, _, _ = _synthetic_2d_spectrum()
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    with pytest.raises(ValueError):
        extract_optimal(data, np.ones((3, 3)), trace)
