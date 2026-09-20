"""`telluric_correction.py`: división real por la transmisión de una
estrella estándar telúrica, escalada por masa de aire, SOLO dentro de
bandas catalogadas (§46)."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.telluric_correction import (
    correct_telluric_absorption,
    measure_standard_transmission,
)
from astrophysics_suite.spectroscopy.telluric_lines import TELLURIC_BANDS

_O2_B = TELLURIC_BANDS[0]  # "O2 B", 6867.0-6884.0
assert _O2_B.name == "O2 B"


def _wavelength_grid(lo=6700.0, hi=7000.0, n=1500):
    return np.linspace(lo, hi, n)


def _gaussian_dip(wavelength, *, center, width, depth):
    return 1.0 - depth * np.exp(-0.5 * ((wavelength - center) / width) ** 2)


def _synthetic_standard(wavelength, *, band_depth=0.6, rng_seed=7):
    """Continuo suave real (polinomio) más una banda telúrica sintética
    de profundidad conocida centrada en la banda O2 B catalogada, más
    ruido gaussiano pequeño -- para poder verificar que la profundidad
    medida (no inventada) coincide con lo inyectado."""
    rng = np.random.default_rng(rng_seed)
    continuum = 1000.0 + 0.05 * (wavelength - wavelength[0])
    band_center = (_O2_B.wavelength_start_angstrom + _O2_B.wavelength_end_angstrom) / 2.0
    dip = _gaussian_dip(wavelength, center=band_center, width=4.0, depth=band_depth)
    flux = continuum * dip + rng.normal(0, 1.0, wavelength.size)
    return flux


def test_measure_standard_transmission_recovers_the_injected_dip_depth():
    wavelength = _wavelength_grid()
    flux = _synthetic_standard(wavelength, band_depth=0.6)

    result = measure_standard_transmission(wavelength, flux)

    band_center = (_O2_B.wavelength_start_angstrom + _O2_B.wavelength_end_angstrom) / 2.0
    idx = int(np.argmin(np.abs(wavelength - band_center)))
    assert result.transmission[idx] == pytest.approx(0.4, abs=0.05)  # 1 - 0.6

    far_idx = int(np.argmin(np.abs(wavelength - 6700.0)))
    assert result.transmission[far_idx] == pytest.approx(1.0, abs=0.05)


def test_correction_removes_a_known_telluric_dip_scaled_to_matching_airmass():
    wavelength = _wavelength_grid()
    standard_flux = _synthetic_standard(wavelength, band_depth=0.6, rng_seed=7)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    science_continuum = 500.0 + 0.02 * (wavelength - wavelength[0])
    band_center = (_O2_B.wavelength_start_angstrom + _O2_B.wavelength_end_angstrom) / 2.0
    science_dip = _gaussian_dip(wavelength, center=band_center, width=4.0, depth=0.6)
    science_flux = science_continuum * science_dip

    result = correct_telluric_absorption(
        wavelength, science_flux, standard_transmission=transmission,
        science_airmass=1.5, standard_airmass=1.5,
    )

    idx = int(np.argmin(np.abs(wavelength - band_center)))
    relative_residual = abs(result.corrected_flux[idx] - science_continuum[idx]) / science_continuum[idx]
    assert relative_residual < 0.1
    assert result.corrected_mask[idx]


def test_correction_never_applied_outside_cataloged_bands_even_with_deep_standard_dip():
    wavelength = _wavelength_grid()
    rng = np.random.default_rng(11)
    # línea fotosférica propia de la estándar, FUERA de cualquier banda telúrica catalogada
    continuum = 1000.0 + rng.normal(0, 0.5, wavelength.size)
    stellar_line = _gaussian_dip(wavelength, center=6750.0, width=2.0, depth=0.8)
    standard_flux = continuum * stellar_line
    transmission = measure_standard_transmission(wavelength, standard_flux)

    science_flux = np.full(wavelength.size, 500.0)
    result = correct_telluric_absorption(
        wavelength, science_flux, standard_transmission=transmission,
        science_airmass=1.2, standard_airmass=1.2,
    )

    idx = int(np.argmin(np.abs(wavelength - 6750.0)))
    assert not result.corrected_mask[idx]
    assert result.correction_factor[idx] == pytest.approx(1.0)
    assert result.corrected_flux[idx] == pytest.approx(science_flux[idx])


def test_airmass_ratio_scales_the_correction_exponent():
    wavelength = _wavelength_grid()
    standard_flux = _synthetic_standard(wavelength, band_depth=0.6, rng_seed=7)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    result_same = correct_telluric_absorption(
        wavelength, np.full(wavelength.size, 500.0), standard_transmission=transmission,
        science_airmass=1.0, standard_airmass=1.0,
    )
    result_double = correct_telluric_absorption(
        wavelength, np.full(wavelength.size, 500.0), standard_transmission=transmission,
        science_airmass=2.0, standard_airmass=1.0,
    )

    band_center = (_O2_B.wavelength_start_angstrom + _O2_B.wavelength_end_angstrom) / 2.0
    idx = int(np.argmin(np.abs(wavelength - band_center)))
    depth_same = 1.0 - result_same.correction_factor[idx]
    depth_double = 1.0 - result_double.correction_factor[idx]
    assert depth_double > depth_same
    assert result_double.airmass_ratio == pytest.approx(2.0)


def test_min_transmission_floor_bounds_the_correction_factor():
    wavelength = _wavelength_grid()
    standard_flux = _synthetic_standard(wavelength, band_depth=0.999, rng_seed=3)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    result = correct_telluric_absorption(
        wavelength, np.full(wavelength.size, 500.0), standard_transmission=transmission,
        science_airmass=3.0, standard_airmass=1.0, min_transmission=0.05,
    )

    assert np.all(result.correction_factor >= 0.05 ** 3.0 - 1e-9)


def test_rejects_non_positive_airmass():
    wavelength = _wavelength_grid()
    standard_flux = _synthetic_standard(wavelength)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    with pytest.raises(ValueError):
        correct_telluric_absorption(
            wavelength, np.full(wavelength.size, 500.0), standard_transmission=transmission,
            science_airmass=0.0, standard_airmass=1.0,
        )
    with pytest.raises(ValueError):
        correct_telluric_absorption(
            wavelength, np.full(wavelength.size, 500.0), standard_transmission=transmission,
            science_airmass=1.0, standard_airmass=-1.0,
        )


def test_no_bands_covered_leaves_flux_untouched():
    wavelength = np.linspace(4000.0, 4500.0, 500)  # fuera de toda banda catalogada
    standard_flux = 1000.0 + np.zeros_like(wavelength)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    science_flux = np.full(wavelength.size, 500.0)
    result = correct_telluric_absorption(
        wavelength, science_flux, standard_transmission=transmission,
        science_airmass=1.5, standard_airmass=1.0,
    )

    assert result.bands_used == ()
    np.testing.assert_array_equal(result.corrected_flux, science_flux)
    assert not np.any(result.corrected_mask)


def test_rejects_mismatched_science_shapes():
    wavelength = _wavelength_grid()
    standard_flux = _synthetic_standard(wavelength)
    transmission = measure_standard_transmission(wavelength, standard_flux)

    with pytest.raises(ValueError):
        correct_telluric_absorption(
            wavelength, np.zeros(10), standard_transmission=transmission,
            science_airmass=1.0, standard_airmass=1.0,
        )
