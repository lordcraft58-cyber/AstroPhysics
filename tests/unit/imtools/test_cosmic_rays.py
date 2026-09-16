"""L.A.Cosmic: debe marcar impactos de rayo cósmico (picos de un píxel,
sin PSF) y NO marcar estrellas reales bien muestreadas, por brillantes
que sean -- esa es la garantía central del algoritmo (ver el docstring
de `cosmic_rays.py`)."""
from __future__ import annotations

import numpy as np

from astrophysics_suite.imtools.cosmic_rays import detect_cosmic_rays


def _star_field_with_cosmic_rays(seed: int = 7):
    rng = np.random.default_rng(seed)
    shape = (80, 80)
    background = 200.0
    field = np.full(shape, background, dtype=np.float64)

    star_positions = [(20, 20), (55, 60), (40, 40)]
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    for x0, y0 in star_positions:
        field += 4000.0 * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * 2.2**2))

    field += rng.normal(0.0, 8.0, shape)  # ruido de lectura ~8 e-, gain=1

    cosmic_ray_positions = [(10, 60), (70, 15), (5, 5)]
    for x0, y0 in cosmic_ray_positions:
        field[y0, x0] += 6000.0  # pico de un solo píxel, sin PSF

    return field, star_positions, cosmic_ray_positions


def test_cosmic_ray_pixels_are_flagged():
    field, _, cosmic_ray_positions = _star_field_with_cosmic_rays()
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=8.0)

    for x0, y0 in cosmic_ray_positions:
        assert result.mask[y0, x0], f"rayo cósmico en ({x0},{y0}) no fue detectado"


def test_star_peaks_are_not_flagged():
    field, star_positions, _ = _star_field_with_cosmic_rays()
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=8.0)

    for x0, y0 in star_positions:
        assert not result.mask[y0, x0], f"estrella real en ({x0},{y0}) fue marcada como rayo cósmico (falso positivo)"


def test_cleaned_data_replaces_spike_with_local_background_estimate():
    field, _, cosmic_ray_positions = _star_field_with_cosmic_rays()
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=8.0)

    for x0, y0 in cosmic_ray_positions:
        assert abs(result.cleaned_data[y0, x0] - 200.0) < 50.0, "el píxel limpiado debería acercarse al fondo local (~200), no al pico"


def test_flags_only_a_small_fraction_of_pixels():
    field, _, _ = _star_field_with_cosmic_rays()
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=8.0)
    assert result.fraction_flagged < 0.01


def test_field_without_cosmic_rays_flags_nothing():
    rng = np.random.default_rng(3)
    shape = (48, 48)
    field = np.full(shape, 150.0) + rng.normal(0.0, 6.0, shape)
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=6.0)
    assert result.n_pixels_flagged == 0
    np.testing.assert_allclose(result.cleaned_data, field)


def test_saturated_pixels_are_excluded_from_detection():
    field, _, _ = _star_field_with_cosmic_rays()
    field[30, 30] = 65000.0  # saturado, no debe tratarse como candidato
    result = detect_cosmic_rays(field, gain_e_per_adu=1.0, read_noise_e=8.0, satlevel=60000.0)
    assert not result.mask[30, 30]


def test_rejects_non_2d_input():
    import pytest

    with pytest.raises(ValueError):
        detect_cosmic_rays(np.zeros((4, 4, 4)))
