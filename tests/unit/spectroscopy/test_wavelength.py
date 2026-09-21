from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.wavelength import (
    fit_wavelength_solution,
    find_arc_lines,
    local_dispersion_at_pixel,
    reidentify_wavelength_solution,
)


def _synthetic_arc_spectrum(n_pixels=1000, line_pixels=(100.3, 300.7, 550.0, 800.2), amplitude=5000.0, seed=0):
    rng = np.random.default_rng(seed)
    x = np.arange(n_pixels, dtype=np.float64)
    spectrum = np.full(n_pixels, 50.0)
    for center in line_pixels:
        spectrum += amplitude * np.exp(-((x - center) ** 2) / (2 * 1.2**2))
    spectrum += rng.normal(0, 3.0, n_pixels)
    return spectrum


def test_find_arc_lines_recovers_known_line_centers():
    true_centers = [100.3, 300.7, 550.0, 800.2]
    spectrum = _synthetic_arc_spectrum(line_pixels=true_centers)
    lines = find_arc_lines(spectrum, min_snr=8.0)

    found_pixels = sorted(line.pixel for line in lines)
    assert len(found_pixels) == len(true_centers)
    for found, true in zip(found_pixels, true_centers):
        assert found == pytest.approx(true, abs=0.3)


def test_find_arc_lines_rejects_non_1d():
    with pytest.raises(ValueError):
        find_arc_lines(np.zeros((5, 5)))


def test_fit_wavelength_solution_recovers_linear_dispersion():
    pixel_centers = [100.0, 300.0, 550.0, 800.0]
    true_wave0, true_dispersion = 4000.0, 2.5  # Å en pixel 0, Å/px
    known_wavelengths = [true_wave0 + true_dispersion * p for p in pixel_centers]

    solution = fit_wavelength_solution(pixel_centers, known_wavelengths, degree=1)
    assert solution.rms_residual < 1e-6
    assert solution.pixel_to_wavelength(0.0) == pytest.approx(true_wave0, abs=1e-6)
    assert solution.pixel_to_wavelength(100.0) == pytest.approx(true_wave0 + 100 * true_dispersion, abs=1e-6)


def test_fit_wavelength_solution_requires_enough_lines():
    with pytest.raises(ValueError):
        fit_wavelength_solution([1.0, 2.0], [4000.0, 4010.0], degree=3)


def test_fit_wavelength_solution_rejects_length_mismatch():
    with pytest.raises(ValueError):
        fit_wavelength_solution([1.0, 2.0, 3.0], [4000.0, 4010.0], degree=1)


def test_reidentify_recovers_known_integer_shift():
    true_centers = [100.0, 300.0, 550.0, 800.0]
    reference_spectrum = _synthetic_arc_spectrum(line_pixels=true_centers, seed=5)

    known_shift = 12  # el nuevo espectro está desplazado +12 px respecto al de referencia
    new_spectrum = np.roll(reference_spectrum, known_shift)

    known_wavelengths = [4000.0 + 2.0 * p for p in true_centers]
    reference_solution = fit_wavelength_solution(true_centers, known_wavelengths, degree=1)

    shifted_solution = reidentify_wavelength_solution(reference_solution, reference_spectrum, new_spectrum, max_shift_px=30)

    # una línea que en el espectro de referencia estaba en `p` ahora está en
    # `p + known_shift` en el nuevo espectro; la solución trasladada debe
    # devolver la misma longitud de onda en esa nueva posición de píxel.
    for pixel, wavelength in zip(true_centers, known_wavelengths):
        assert shifted_solution.pixel_to_wavelength(pixel + known_shift) == pytest.approx(wavelength, abs=0.5)


def test_reidentify_rejects_shape_mismatch():
    reference_solution = fit_wavelength_solution([1.0, 2.0, 3.0], [4000.0, 4010.0, 4020.0], degree=1)
    with pytest.raises(ValueError):
        reidentify_wavelength_solution(reference_solution, np.zeros(10), np.zeros(20))


def test_local_dispersion_at_pixel_recovers_known_linear_dispersion():
    pixel_centers = [100.0, 300.0, 550.0, 800.0]
    true_dispersion = 2.5  # Å/px
    known_wavelengths = [4000.0 + true_dispersion * p for p in pixel_centers]
    solution = fit_wavelength_solution(pixel_centers, known_wavelengths, degree=1)

    for pixel in (0.0, 400.0, 999.0):
        assert local_dispersion_at_pixel(solution, pixel) == pytest.approx(true_dispersion, abs=1e-6)


def test_local_dispersion_at_pixel_varies_along_a_nonlinear_solution():
    # una solución cuadrática real tiene dispersión LOCAL distinta en
    # cada extremo -- justo lo que una dispersión media global (CDELT1)
    # no puede capturar, y la razón de tener una función por-píxel real.
    pixel_centers = [0.0, 250.0, 500.0, 750.0, 999.0]
    known_wavelengths = [4000.0 + 2.0 * p + 0.001 * p**2 for p in pixel_centers]
    solution = fit_wavelength_solution(pixel_centers, known_wavelengths, degree=2)

    dispersion_low = local_dispersion_at_pixel(solution, 10.0)
    dispersion_high = local_dispersion_at_pixel(solution, 990.0)
    assert dispersion_high > dispersion_low  # dλ/dpx = 2 + 0.002*p, creciente en p
    assert dispersion_low == pytest.approx(2.0 + 0.002 * 10.0, abs=0.05)
    assert dispersion_high == pytest.approx(2.0 + 0.002 * 990.0, abs=0.05)
