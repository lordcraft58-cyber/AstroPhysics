from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.fluxcal import (
    apply_extinction_correction,
    build_sensitivity_function,
    calibrate_flux,
    compute_airmass_kasten_young,
    compute_airmass_secant,
)


def test_airmass_at_zenith_is_approximately_one():
    # Kasten-Young es un ajuste empírico, no forzado a pasar exactamente
    # por 1.0 en z=0 -- 0.9997 es el valor real de la fórmula publicada.
    assert compute_airmass_kasten_young(0.0) == pytest.approx(1.0, abs=1e-3)
    assert compute_airmass_secant(0.0) == pytest.approx(1.0, abs=1e-6)


def test_airmass_kasten_young_matches_secant_at_moderate_zenith_angle():
    # ambas fórmulas coinciden bien para z moderado; divergen cerca del horizonte
    z = 30.0
    assert compute_airmass_kasten_young(z) == pytest.approx(compute_airmass_secant(z), rel=0.01)


def test_airmass_kasten_young_stays_finite_near_horizon_unlike_secant():
    z = 89.9
    ky = compute_airmass_kasten_young(z)
    secant = compute_airmass_secant(z)
    assert math.isfinite(ky)
    assert ky < secant  # la secante sobreestima drásticamente cerca del horizonte


def test_airmass_rejects_out_of_range_zenith_angle():
    with pytest.raises(ValueError):
        compute_airmass_kasten_young(95.0)
    with pytest.raises(ValueError):
        compute_airmass_secant(-1.0)


def test_extinction_correction_increases_flux_for_positive_coefficient():
    corrected = apply_extinction_correction(np.array([100.0]), extinction_mag_per_airmass=0.2, airmass=1.5)
    assert corrected[0] > 100.0


def test_extinction_correction_rejects_non_positive_airmass():
    with pytest.raises(ValueError):
        apply_extinction_correction(np.array([100.0]), extinction_mag_per_airmass=0.2, airmass=0.0)


def test_build_sensitivity_function_recovers_known_response_and_calibrates_correctly():
    wavelength = np.linspace(4000.0, 7000.0, 60)
    true_response = 1e-16 * (1.0 + 0.1 * np.sin(wavelength / 500.0))  # respuesta instrumental suave conocida
    true_stellar_flux = 1e-13 * (wavelength / 5000.0) ** -2  # espectro "verdadero" de la estándar

    observed_counts = true_stellar_flux / true_response  # cuentas/s medidas, sin ruido
    airmass = 1.2
    k = 0.15
    observed_counts_extincted = observed_counts / (10.0 ** (0.4 * k * airmass))  # lo que realmente se mide, atenuado

    sensitivity = build_sensitivity_function(
        wavelength, observed_counts_extincted, wavelength, true_stellar_flux, airmass=airmass, extinction_mag_per_airmass=k, poly_degree=4
    )
    recovered_response_inverse = sensitivity.evaluate(wavelength)
    np.testing.assert_allclose(recovered_response_inverse, true_response, rtol=0.02)

    # calibrar la propia estrella estándar con su función de sensibilidad
    # debe devolver, aproximadamente, su flujo verdadero conocido.
    calibrated = calibrate_flux(wavelength, observed_counts_extincted, sensitivity, airmass=airmass, extinction_mag_per_airmass=k)
    np.testing.assert_allclose(calibrated, true_stellar_flux, rtol=0.02)


def test_build_sensitivity_function_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        build_sensitivity_function(np.zeros(5), np.zeros(4), np.zeros(5), np.zeros(5), airmass=1.0)
