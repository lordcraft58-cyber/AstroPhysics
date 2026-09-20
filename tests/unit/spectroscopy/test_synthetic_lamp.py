"""`synthetic_lamp.py`: generadores para pruebas -- deben producir
exactamente lo que dicen (líneas donde afirman, defectos donde
afirman), o toda validación posterior construida encima sería sobre
arena (§33)."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.line_catalog import NEON_ARC_LINES
from astrophysics_suite.spectroscopy.synthetic_lamp import (
    apply_gaussian_seeing,
    generate_synthetic_lamp_frame2d,
    generate_synthetic_lamp_spectrum,
)


def test_1d_spectrum_injects_lines_at_the_exact_predicted_pixel():
    spectrum = generate_synthetic_lamp_spectrum(
        "Ne", n_pixels=1024, wavelength_at_pixel0=5700.0, dispersion_angstrom_per_px=1.4, seed=3,
    )
    assert len(spectrum.injected_lines) > 5
    for pixel, line in spectrum.injected_lines:
        expected_pixel = (line.wavelength_air_angstrom - 5700.0) / 1.4
        assert pixel == pytest.approx(expected_pixel, abs=1e-6)
        # y debe haber una elevación de flujo real en esa posición
        idx = int(round(pixel))
        assert spectrum.flux[idx] > np.median(spectrum.flux)


def test_1d_spectrum_only_injects_lines_that_fall_in_range():
    narrow = generate_synthetic_lamp_spectrum(
        "Ne", n_pixels=100, wavelength_at_pixel0=5700.0, dispersion_angstrom_per_px=0.5, seed=1,
    )
    for _, line in narrow.injected_lines:
        assert 5700.0 <= line.wavelength_air_angstrom <= 5700.0 + 0.5 * 100


def test_2d_frame_trace_follows_the_declared_center_and_curvature():
    frame = generate_synthetic_lamp_frame2d(
        "Ne", shape=(60, 1024), trace_row_center=30.0, curvature_px=0.0, seed=5,
        wavelength_at_pixel0=5700.0, dispersion_angstrom_per_px=1.4,
    )
    assert len(frame.injected_lines) > 0
    # sin curvatura: el perfil espacial pico debe caer en la fila 30 en
    # la columna de una linea real inyectada (con senal de verdad, no
    # solo fondo + ruido)
    line_pixel = int(round(frame.injected_lines[0][0]))
    profile_at_line = frame.data[:, line_pixel]
    assert np.argmax(profile_at_line) == pytest.approx(30, abs=2)


def test_2d_frame_cosmic_rays_are_really_at_the_reported_positions():
    frame = generate_synthetic_lamp_frame2d("Ne", shape=(60, 1024), n_cosmic_rays=5, seed=9, cosmic_ray_amplitude=50000.0)
    assert len(frame.cosmic_ray_pixels) == 5
    for row, col in frame.cosmic_ray_pixels:
        assert frame.data[row, col] > 10000.0  # el pico inyectado domina el valor del pixel


def test_2d_frame_dead_pixels_are_really_zero_at_the_reported_positions():
    frame = generate_synthetic_lamp_frame2d("Ne", shape=(60, 1024), n_dead_pixels=4, seed=11)
    assert len(frame.dead_pixels) == 4
    for row, col in frame.dead_pixels:
        assert frame.data[row, col] == 0.0


def test_2d_frame_rejects_a_center_outside_the_image():
    with pytest.raises(ValueError):
        generate_synthetic_lamp_frame2d("Ne", shape=(20, 100), trace_row_center=99.0)


def test_apply_gaussian_seeing_smooths_without_changing_total_flux():
    data = np.zeros((50, 50))
    data[25, 25] = 1000.0
    smoothed = apply_gaussian_seeing(data, sigma_px=2.0)
    assert smoothed[25, 25] < 1000.0  # el pico se reparte
    np.testing.assert_allclose(smoothed.sum(), data.sum(), rtol=1e-6)


def test_apply_gaussian_seeing_is_a_no_op_for_zero_sigma():
    data = np.random.default_rng(0).normal(size=(10, 10))
    np.testing.assert_array_equal(apply_gaussian_seeing(data, sigma_px=0.0), data)


def test_arc_catalog_used_matches_neon_reference():
    """El propio generador usa el catálogo real, no una lista propia
    duplicada -- si NEON_ARC_LINES cambiara, el generador cambiaría con
    él, nunca podrían divergir en silencio."""
    spectrum = generate_synthetic_lamp_spectrum("Ne", n_pixels=2000, wavelength_at_pixel0=3800.0, seed=0)
    injected_wavelengths = {line.wavelength_air_angstrom for _, line in spectrum.injected_lines}
    catalog_in_range = {
        line.wavelength_air_angstrom for line in NEON_ARC_LINES
        if 3800.0 <= line.wavelength_air_angstrom <= 3800.0 + 1.4 * 1999
    }
    assert injected_wavelengths == catalog_in_range
