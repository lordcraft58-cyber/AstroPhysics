"""`template_comparison.py` (§25): comparación visual observado/plantilla
sobre el eje real del observado -- nunca clasifica, nunca extrapola la
plantilla más allá de su rango real."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.template_comparison import compare_to_template


def _synthetic_spectrum(wave0=4000.0, dispersion=2.0, width=500, seed=1):
    rng = np.random.default_rng(seed)
    pixel = np.arange(width, dtype=np.float64)
    wavelength = wave0 + dispersion * pixel
    flux = 100.0 - 20.0 * np.exp(-((pixel - 200.0) ** 2) / (2 * 5.0**2)) + rng.normal(0, 0.2, width)
    return wavelength, flux


def test_compare_to_template_recovers_a_near_zero_residual_for_an_identical_spectrum():
    wavelength, flux = _synthetic_spectrum(seed=1)
    result = compare_to_template(wavelength, flux, wavelength, flux, normalize="none")
    np.testing.assert_allclose(result.residual, 0.0, atol=1e-9)
    assert result.overlap_fraction == pytest.approx(1.0)


def test_compare_to_template_median_normalization_cancels_a_constant_flux_scale_factor():
    wavelength, flux = _synthetic_spectrum(seed=2)
    scaled_template_flux = flux * 5.0  # mismo espectro, unidades/nivel de flujo absoluto distinto
    result = compare_to_template(wavelength, flux, wavelength, scaled_template_flux, normalize="median")
    np.testing.assert_allclose(result.residual, 0.0, atol=1e-6)


def test_compare_to_template_none_normalization_keeps_the_raw_flux_difference():
    wavelength, flux = _synthetic_spectrum(seed=3)
    template_flux = flux + 10.0  # desplazamiento aditivo real conocido
    result = compare_to_template(wavelength, flux, wavelength, template_flux, normalize="none")
    assert result.observed_scale == 1.0
    assert result.template_scale == 1.0
    np.testing.assert_allclose(result.residual, -10.0, atol=1e-9)


def test_compare_to_template_reports_nan_outside_the_real_template_range():
    wavelength, flux = _synthetic_spectrum(width=500, seed=4)
    # la plantilla solo cubre la primera mitad del rango observado
    template_wavelength = wavelength[:250]
    template_flux = flux[:250]
    result = compare_to_template(wavelength, flux, template_wavelength, template_flux, normalize="none")
    assert 0.0 < result.overlap_fraction < 1.0
    assert np.all(np.isfinite(result.residual[:250]))
    assert np.all(np.isnan(result.residual[251:]))


def test_compare_to_template_rejects_a_template_with_no_real_overlap():
    wavelength, flux = _synthetic_spectrum(wave0=4000.0, width=500, seed=5)
    template_wavelength = wavelength + 100000.0  # rango completamente disjunto
    with pytest.raises(ValueError, match="no solapa"):
        compare_to_template(wavelength, flux, template_wavelength, flux, normalize="none")


def test_compare_to_template_rejects_shape_mismatches():
    wavelength, flux = _synthetic_spectrum(seed=6)
    with pytest.raises(ValueError):
        compare_to_template(wavelength, flux[:-1], wavelength, flux, normalize="none")
    with pytest.raises(ValueError):
        compare_to_template(wavelength, flux, wavelength, flux[:-1], normalize="none")


def test_compare_to_template_rejects_an_unknown_normalization():
    wavelength, flux = _synthetic_spectrum(seed=7)
    with pytest.raises(ValueError, match="normalize"):
        compare_to_template(wavelength, flux, wavelength, flux, normalize="bogus")


def test_compare_to_template_divide_recovers_a_ratio_of_one_for_an_identical_spectrum():
    wavelength, flux = _synthetic_spectrum(seed=9)
    result = compare_to_template(wavelength, flux, wavelength, flux, normalize="none", operation="divide")
    assert result.operation == "divide"
    np.testing.assert_allclose(result.residual, 1.0, atol=1e-9)


def test_compare_to_template_divide_recovers_a_known_real_ratio():
    wavelength, flux = _synthetic_spectrum(seed=10)
    template_flux = flux * 2.0  # factor real conocido
    result = compare_to_template(wavelength, flux, wavelength, template_flux, normalize="none", operation="divide")
    np.testing.assert_allclose(result.residual, 0.5, atol=1e-9)


def test_compare_to_template_divide_reports_nan_where_the_template_is_exactly_zero():
    wavelength = np.array([4000.0, 4001.0, 4002.0])
    flux = np.array([10.0, 20.0, 30.0])
    template_flux = np.array([5.0, 0.0, 15.0])
    result = compare_to_template(wavelength, flux, wavelength, template_flux, normalize="none", operation="divide")
    assert np.isfinite(result.residual[0])
    assert np.isnan(result.residual[1])
    assert np.isfinite(result.residual[2])


def test_compare_to_template_default_operation_is_subtract():
    wavelength, flux = _synthetic_spectrum(seed=11)
    result = compare_to_template(wavelength, flux, wavelength, flux, normalize="none")
    assert result.operation == "subtract"


def test_compare_to_template_rejects_an_unknown_operation():
    wavelength, flux = _synthetic_spectrum(seed=12)
    with pytest.raises(ValueError, match="operation"):
        compare_to_template(wavelength, flux, wavelength, flux, normalize="none", operation="bogus")


def test_compare_to_template_rejects_a_template_with_fewer_than_two_points():
    wavelength, flux = _synthetic_spectrum(seed=8)
    with pytest.raises(ValueError, match="dos puntos"):
        compare_to_template(wavelength, flux, wavelength[:1], flux[:1], normalize="none")
