from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.bad_pixel_mask import (
    build_bad_pixel_mask,
    flag_hot_and_cold_pixels_from_dark,
    interpolate_bad_pixels,
    smooth_bad_pixel_map,
)


def test_build_bad_pixel_mask_flags_outside_thresholds():
    flat = np.ones((4, 4))
    flat[0, 0] = 0.1  # muerto
    flat[1, 1] = 2.0  # caliente/saturado
    mask = build_bad_pixel_mask(flat, low_threshold=0.5, high_threshold=1.5)
    assert mask[0, 0]
    assert mask[1, 1]
    assert not mask[2, 2]


def test_build_bad_pixel_mask_rejects_invalid_thresholds():
    with pytest.raises(ValueError):
        build_bad_pixel_mask(np.ones((2, 2)), low_threshold=1.5, high_threshold=1.0)


def test_interpolate_bad_pixels_linear_along_axis():
    data = np.array([[10.0, 20.0, 999.0, 40.0, 50.0]])
    mask = np.array([[False, False, True, False, False]])
    result = interpolate_bad_pixels(data, mask, axis=1)
    assert result[0, 2] == pytest.approx(30.0)


def test_interpolate_bad_pixels_edge_extrapolates_constant():
    data = np.array([[999.0, 20.0, 30.0]])
    mask = np.array([[True, False, False]])
    result = interpolate_bad_pixels(data, mask, axis=1)
    assert result[0, 0] == pytest.approx(20.0)


def test_interpolate_bad_pixels_shape_mismatch_raises():
    with pytest.raises(ValueError):
        interpolate_bad_pixels(np.zeros((2, 2)), np.zeros((3, 3), dtype=bool))


def test_flag_hot_and_cold_pixels_from_dark():
    dark = np.full((10, 10), 5.0)
    dark[5, 5] = 500.0
    mask = flag_hot_and_cold_pixels_from_dark(dark, n_sigma=8.0)
    assert mask[5, 5]
    assert not mask[0, 0]


def test_smooth_bad_pixel_map_dilates():
    mask = np.zeros((5, 5), dtype=bool)
    mask[2, 2] = True
    grown = smooth_bad_pixel_map(mask, dilate_iterations=1)
    assert grown[2, 1] and grown[2, 3] and grown[1, 2] and grown[3, 2]
    assert not grown[0, 0]


def test_smooth_bad_pixel_map_no_dilation_returns_same():
    mask = np.zeros((3, 3), dtype=bool)
    mask[1, 1] = True
    result = smooth_bad_pixel_map(mask, dilate_iterations=0)
    np.testing.assert_array_equal(result, mask)
