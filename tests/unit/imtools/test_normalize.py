from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.imtools.normalize import normalize_minmax, normalize_percentile, normalize_sigma_clip


def test_normalize_minmax_maps_to_zero_one():
    data = np.array([10.0, 20.0, 30.0, 40.0, 50.0])

    normalized = normalize_minmax(data)

    assert normalized.min() == pytest.approx(0.0)
    assert normalized.max() == pytest.approx(1.0)
    np.testing.assert_allclose(normalized, [0.0, 0.25, 0.5, 0.75, 1.0])


def test_normalize_minmax_rejects_constant_image():
    with pytest.raises(ValueError):
        normalize_minmax(np.full((5, 5), 42.0))


def test_normalize_minmax_excludes_non_finite_from_range_but_keeps_shape():
    data = np.array([1.0, 2.0, 3.0, np.nan])

    normalized = normalize_minmax(data)

    assert normalized.shape == data.shape
    assert np.isnan(normalized[3])
    np.testing.assert_allclose(normalized[:3], [0.0, 0.5, 1.0])


def test_normalize_percentile_is_robust_to_extreme_outliers_unlike_minmax():
    rng = np.random.default_rng(0)
    bulk_data = rng.normal(100.0, 5.0, 998)
    data = np.concatenate([bulk_data, [50.0, 100000.0]])  # dos outliers extremos, aislados

    minmax_bulk_std = normalize_minmax(data)[:998].std()
    percentile_bulk_std = normalize_percentile(data, low=1.0, high=99.0)[:998].std()

    # minmax queda con el rango dominado por el outlier de 100000 -> el
    # grueso de los datos se aplasta casi a un punto; la normalización
    # por percentiles conserva su dispersión real, órdenes de magnitud más
    assert percentile_bulk_std > 100 * minmax_bulk_std


def test_normalize_percentile_rejects_invalid_bounds():
    with pytest.raises(ValueError):
        normalize_percentile(np.arange(10.0), low=99.0, high=1.0)


def test_normalize_sigma_clip_recovers_known_z_scores():
    data = np.array([90.0, 95.0, 100.0, 105.0, 110.0])
    # mediana=100, MAD=5 -> sigma robusta = 5*1.4826

    z = normalize_sigma_clip(data, clip=False)

    expected_sigma = 5.0 * 1.4826
    np.testing.assert_allclose(z, (data - 100.0) / expected_sigma, rtol=1e-6)


def test_normalize_sigma_clip_clips_to_n_sigma_by_default():
    data = np.array([100.0, 100.0, 100.0, 100.0, 100000.0])  # un solo outlier extremo

    z = normalize_sigma_clip(data, n_sigma=3.0)

    assert z.max() == pytest.approx(3.0)
    assert z.min() >= -3.0


def test_normalize_sigma_clip_rejects_invalid_center():
    with pytest.raises(ValueError):
        normalize_sigma_clip(np.arange(10.0), center="mode")
