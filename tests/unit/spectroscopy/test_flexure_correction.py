"""`flexure_correction.py`: SOLO el desplazamiento global entre
exposiciones (§44) -- nunca recalcula el polinomio completo, reutiliza
`reidentify_wavelength_solution` ya probado."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.flexure_correction import measure_flexure_shift
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

_C_KM_S = 299792.458


def _linear_solution(dispersion=1.4, zero_point=4500.0, n_lines=8, seed=41):
    rng = np.random.default_rng(seed)
    pixels = np.sort(rng.uniform(20, 980, size=n_lines))
    wavelengths = dispersion * pixels + zero_point
    return fit_wavelength_solution(list(pixels), list(wavelengths), degree=1)


def _arc_row(*, width=1000, shift=0.0, seed=3, lines=(200.0, 500.0, 800.0)):
    rng = np.random.default_rng(seed)
    row = np.full(width, 100.0) + rng.normal(0, 2.0, width)
    for p in lines:
        idx = int(round(p + shift))
        row[idx - 2 : idx + 3] += np.array([80, 600, 1500, 600, 80])
    return row


def test_measures_a_real_shift_within_the_known_precision_of_cross_correlation():
    solution = _linear_solution(dispersion=1.4)
    reference_spectrum = _arc_row(shift=0.0)
    true_shift_px = 2.7
    new_spectrum = _arc_row(shift=true_shift_px)

    result = measure_flexure_shift(solution, reference_spectrum, new_spectrum, reference_wavelength=5200.0)

    # misma precisión ya establecida para reidentify_wavelength_solution
    # en la slice 3 (test_reidentify_profile_offset_recovers_the_true_shift)
    assert result.shift_px == pytest.approx(true_shift_px, abs=0.5)


def test_shift_angstrom_matches_the_known_linear_dispersion():
    dispersion = 1.4
    solution = _linear_solution(dispersion=dispersion)
    reference_spectrum = _arc_row(shift=0.0)
    new_spectrum = _arc_row(shift=3.0)

    result = measure_flexure_shift(solution, reference_spectrum, new_spectrum, reference_wavelength=5200.0)

    assert result.shift_angstrom == pytest.approx(result.shift_px * dispersion, rel=1e-6)


def test_shift_velocity_matches_the_classical_doppler_formula():
    solution = _linear_solution()
    reference_spectrum = _arc_row(shift=0.0)
    new_spectrum = _arc_row(shift=3.0)
    reference_wavelength = 5200.0

    result = measure_flexure_shift(solution, reference_spectrum, new_spectrum, reference_wavelength=reference_wavelength)

    expected_velocity = _C_KM_S * result.shift_angstrom / reference_wavelength
    assert result.shift_velocity_km_s == pytest.approx(expected_velocity, rel=1e-6)


def test_no_real_shift_gives_a_shift_close_to_zero():
    solution = _linear_solution()
    spectrum = _arc_row(shift=0.0)

    result = measure_flexure_shift(solution, spectrum, spectrum.copy(), reference_wavelength=5200.0)

    assert result.shift_px == pytest.approx(0.0, abs=0.5)
    assert result.shift_angstrom == pytest.approx(0.0, abs=1.0)


def test_shifted_solution_preserves_the_original_polynomial_shape():
    """El punto central del encargo (§44): nunca recalcular el
    polinomio completo -- solo el desplazamiento."""
    solution = _linear_solution()
    reference_spectrum = _arc_row(shift=0.0)
    new_spectrum = _arc_row(shift=2.0)

    result = measure_flexure_shift(solution, reference_spectrum, new_spectrum, reference_wavelength=5200.0)

    np.testing.assert_array_equal(result.shifted_solution.coefficients, solution.coefficients)
    assert result.shifted_solution.degree == solution.degree


def test_rejects_mismatched_spectrum_shapes():
    solution = _linear_solution()
    with pytest.raises(ValueError):
        measure_flexure_shift(solution, np.zeros(100), np.zeros(50), reference_wavelength=5000.0)


def test_result_carries_the_reference_wavelength_used():
    solution = _linear_solution()
    reference_spectrum = _arc_row(shift=0.0)
    new_spectrum = _arc_row(shift=1.0)

    result = measure_flexure_shift(solution, reference_spectrum, new_spectrum, reference_wavelength=5300.0)
    assert result.reference_wavelength == 5300.0
