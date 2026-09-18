from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.imtools.statistics import compute_histogram, compute_image_statistics


def test_compute_image_statistics_on_known_array():
    data = np.arange(1, 101, dtype=np.float64).reshape(10, 10)  # 1..100

    stats = compute_image_statistics(data)

    assert stats.n_pixels == 100
    assert stats.mean == pytest.approx(50.5)
    assert stats.median == pytest.approx(50.5)
    assert stats.minimum == pytest.approx(1.0)
    assert stats.maximum == pytest.approx(100.0)
    assert stats.percentile_1 < stats.percentile_5 < stats.median < stats.percentile_95 < stats.percentile_99


def test_compute_image_statistics_excludes_non_finite_values():
    data = np.array([[1.0, 2.0, np.nan], [3.0, np.inf, 4.0]])

    stats = compute_image_statistics(data)

    assert stats.n_pixels == 4
    assert stats.mean == pytest.approx(2.5)
    assert stats.maximum == pytest.approx(4.0)


def test_compute_image_statistics_rejects_all_non_finite():
    with pytest.raises(ValueError):
        compute_image_statistics(np.full((3, 3), np.nan))


def test_compute_image_statistics_mad_sigma_close_to_std_for_gaussian_data():
    rng = np.random.default_rng(0)
    data = rng.normal(100.0, 5.0, (200, 200))

    stats = compute_image_statistics(data)

    assert stats.mad_sigma == pytest.approx(5.0, rel=0.1)
    assert stats.std == pytest.approx(5.0, rel=0.1)


def test_compute_image_statistics_mad_sigma_robust_to_outliers_unlike_std():
    data = np.full((20, 20), 100.0)
    data[0, 0] = 100000.0  # un solo píxel extremo (rayo cósmico)

    stats = compute_image_statistics(data)

    assert stats.mad_sigma < 1.0  # el resto de la imagen es constante -- MAD lo ve
    assert stats.std > 1000.0  # std clásica queda dominada por el outlier


def test_compute_histogram_counts_sum_to_pixel_count():
    data = np.linspace(0.0, 1.0, 1000)

    hist = compute_histogram(data, bins=10)

    assert hist.counts.sum() == 1000
    assert len(hist.bin_edges) == 11


def test_compute_histogram_excludes_non_finite_values():
    data = np.array([1.0, 2.0, 3.0, np.nan, np.inf])

    hist = compute_histogram(data, bins=3)

    assert hist.counts.sum() == 3


def test_compute_histogram_rejects_non_positive_bins():
    with pytest.raises(ValueError):
        compute_histogram(np.arange(10), bins=0)


def test_compute_histogram_rejects_all_non_finite():
    with pytest.raises(ValueError):
        compute_histogram(np.full(5, np.nan))
