from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.overscan import subtract_overscan


def test_median_overscan_removes_per_row_bias_gradient():
    rows, science_cols, overscan_cols = 6, 10, 4
    total_cols = science_cols + overscan_cols
    data = np.zeros((rows, total_cols))
    row_bias = np.arange(rows, dtype=np.float64) * 5.0 + 1000.0  # gradiente de bias por fila
    data[:, :science_cols] = 50.0 + row_bias[:, np.newaxis]
    data[:, science_cols:] = row_bias[:, np.newaxis]  # la franja de overscan solo mide el bias

    result = subtract_overscan(
        data,
        overscan_region=(slice(None), slice(science_cols, total_cols)),
        trim_region=(slice(None), slice(0, science_cols)),
        fit_axis=0,
        function="median",
    )
    np.testing.assert_allclose(result.data, 50.0)
    assert result.data.shape == (rows, science_cols)
    np.testing.assert_allclose(result.overscan_level, row_bias)


def test_polynomial_overscan_smooths_noisy_profile():
    rng = np.random.default_rng(0)
    rows, overscan_cols = 40, 6
    data = np.zeros((rows, overscan_cols))
    true_profile = 1000.0 + 0.5 * np.arange(rows)
    data[:, :] = true_profile[:, np.newaxis] + rng.normal(0, 3.0, (rows, overscan_cols))

    result = subtract_overscan(
        data, overscan_region=(slice(None), slice(None)), fit_axis=0, function="polynomial", poly_degree=1
    )
    np.testing.assert_allclose(result.overscan_level, true_profile, atol=2.0)


def test_invalid_function_raises():
    with pytest.raises(ValueError):
        subtract_overscan(np.zeros((4, 4)), overscan_region=(slice(None), slice(0, 2)), function="spline")


def test_invalid_fit_axis_raises():
    with pytest.raises(ValueError):
        subtract_overscan(np.zeros((4, 4)), overscan_region=(slice(None), slice(0, 2)), fit_axis=2)
