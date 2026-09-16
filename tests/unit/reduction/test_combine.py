from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.combine import combine_images


def test_median_combine_matches_plain_median_without_outliers():
    rng = np.random.default_rng(1)
    images = [np.full((5, 5), 100.0) + rng.normal(0, 1.0, (5, 5)) for _ in range(7)]
    result = combine_images(images, method="median", sigma_clip=None)
    np.testing.assert_allclose(result.data, np.median(np.stack(images), axis=0))
    np.testing.assert_array_equal(result.n_combined, 7)


def test_sigma_clip_rejects_single_outlier_pixel():
    images = [np.full((3, 3), 100.0) for _ in range(9)]
    images[4] = images[4].copy()
    images[4][1, 1] = 100000.0  # un solo fotograma con un rayo cósmico en ese píxel

    result = combine_images(images, method="median", sigma_clip=3.0)
    assert result.data[1, 1] == pytest.approx(100.0)
    assert result.n_combined[1, 1] == 8  # el outlier fue rechazado
    untouched = result.n_combined.copy()
    untouched[1, 1] = 9
    np.testing.assert_array_equal(untouched, 9)  # ningún otro píxel perdió fotogramas


def test_mean_combine_mode():
    images = [np.full((2, 2), value) for value in (10.0, 20.0, 30.0)]
    result = combine_images(images, method="mean", sigma_clip=None)
    np.testing.assert_allclose(result.data, 20.0)


def test_rejects_empty_list():
    with pytest.raises(ValueError):
        combine_images([])


def test_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        combine_images([np.zeros((2, 2)), np.zeros((3, 3))])


def test_rejects_invalid_method():
    with pytest.raises(ValueError):
        combine_images([np.zeros((2, 2))], method="sum")


def test_single_image_combine_has_zero_uncertainty():
    result = combine_images([np.full((2, 2), 42.0)], method="median", sigma_clip=None)
    np.testing.assert_allclose(result.data, 42.0)
    np.testing.assert_allclose(result.uncertainty, 0.0)
