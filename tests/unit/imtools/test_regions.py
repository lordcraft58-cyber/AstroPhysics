from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.imtools.regions import circular_mask, crop, rectangular_mask


def test_crop_returns_expected_subregion():
    data = np.arange(100).reshape(10, 10)

    cropped = crop(data, (slice(2, 5), slice(3, 7)))

    assert cropped.shape == (3, 4)
    np.testing.assert_array_equal(cropped, data[2:5, 3:7])


def test_crop_rejects_non_2d_input():
    with pytest.raises(ValueError):
        crop(np.zeros((3, 3, 3)), (slice(0, 1), slice(0, 1)))


def test_crop_rejects_empty_region():
    data = np.zeros((10, 10))
    with pytest.raises(ValueError):
        crop(data, (slice(5, 5), slice(0, 3)))


def test_rectangular_mask_marks_only_the_region():
    mask = rectangular_mask((10, 10), (slice(2, 5), slice(3, 6)))

    assert mask.shape == (10, 10)
    assert mask.sum() == 3 * 3
    assert mask[3, 4]
    assert not mask[0, 0]


def test_circular_mask_marks_pixels_within_radius():
    mask = circular_mask((21, 21), center=(10, 10), radius=5.0)

    assert mask[10, 10]  # centro
    assert mask[10, 14]  # a 4px, dentro
    assert not mask[10, 20]  # a 10px, fuera
    # área aproximada de un círculo de radio 5 (sin antialiasing subpíxel)
    assert abs(mask.sum() - np.pi * 5.0**2) < 15


def test_circular_mask_rejects_non_positive_radius():
    with pytest.raises(ValueError):
        circular_mask((10, 10), center=(5, 5), radius=0.0)
