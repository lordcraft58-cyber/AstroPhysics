"""`UncertainImage`: propagación de incertidumbre verificada contra las
fórmulas analíticas estándar (no solo "el resultado tiene la forma
correcta") -- suma en cuadratura para +/-, propagación relativa para
*//."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.imtools.arithmetic import UncertainImage


def test_from_counts_matches_poisson_plus_read_noise_analytically():
    data = np.array([[100.0, 400.0], [0.0, 900.0]])
    image = UncertainImage.from_counts(data, gain_e_per_adu=2.0, read_noise_e=5.0)

    expected_variance_e = data * 2.0 + 5.0**2
    expected_uncertainty_adu = np.sqrt(expected_variance_e) / 2.0
    np.testing.assert_allclose(image.uncertainty, expected_uncertainty_adu)


def test_from_counts_rejects_non_positive_gain():
    with pytest.raises(ValueError):
        UncertainImage.from_counts(np.ones((2, 2)), gain_e_per_adu=0.0)


def test_addition_propagates_uncertainty_in_quadrature():
    a = UncertainImage(data=np.full((2, 2), 10.0), uncertainty=np.full((2, 2), 3.0))
    b = UncertainImage(data=np.full((2, 2), 4.0), uncertainty=np.full((2, 2), 4.0))

    result = a + b
    np.testing.assert_allclose(result.data, 14.0)
    np.testing.assert_allclose(result.uncertainty, 5.0)  # sqrt(3^2+4^2) = 5


def test_subtraction_propagates_uncertainty_in_quadrature():
    a = UncertainImage(data=np.full((2, 2), 10.0), uncertainty=np.full((2, 2), 3.0))
    b = UncertainImage(data=np.full((2, 2), 4.0), uncertainty=np.full((2, 2), 4.0))

    result = a - b
    np.testing.assert_allclose(result.data, 6.0)
    np.testing.assert_allclose(result.uncertainty, 5.0)


def test_scalar_addition_leaves_uncertainty_unchanged():
    a = UncertainImage(data=np.full((2, 2), 10.0), uncertainty=np.full((2, 2), 3.0))
    result = a + 5.0
    np.testing.assert_allclose(result.data, 15.0)
    np.testing.assert_allclose(result.uncertainty, 3.0)


def test_multiplication_by_flat_field_propagates_relative_uncertainty():
    science = UncertainImage(data=np.full((2, 2), 1000.0), uncertainty=np.full((2, 2), 30.0))  # 3% relativo
    flat = UncertainImage(data=np.full((2, 2), 1.0), uncertainty=np.full((2, 2), 0.04))  # 4% relativo

    result = science * flat
    np.testing.assert_allclose(result.data, 1000.0)
    expected_relative = np.sqrt(0.03**2 + 0.04**2)
    np.testing.assert_allclose(result.uncertainty, 1000.0 * expected_relative, rtol=1e-9)


def test_division_by_flat_field_propagates_relative_uncertainty():
    science = UncertainImage(data=np.full((2, 2), 1000.0), uncertainty=np.full((2, 2), 30.0))
    flat = UncertainImage(data=np.full((2, 2), 2.0), uncertainty=np.full((2, 2), 0.08))  # 4% relativo

    result = science / flat
    np.testing.assert_allclose(result.data, 500.0)
    expected_relative = np.sqrt(0.03**2 + 0.04**2)
    np.testing.assert_allclose(result.uncertainty, 500.0 * expected_relative, rtol=1e-9)


def test_division_by_scalar_zero_raises():
    a = UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((2, 2)))
    with pytest.raises(ZeroDivisionError):
        a / 0


def test_masks_combine_with_logical_or():
    mask_a = np.array([[True, False], [False, False]])
    mask_b = np.array([[False, False], [False, True]])
    a = UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((2, 2)), mask=mask_a)
    b = UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((2, 2)), mask=mask_b)

    result = a + b
    np.testing.assert_array_equal(result.mask, mask_a | mask_b)


def test_shape_mismatch_raises():
    with pytest.raises(ValueError):
        UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((3, 3)))


def test_negative_uncertainty_raises():
    with pytest.raises(ValueError):
        UncertainImage(data=np.ones((2, 2)), uncertainty=np.full((2, 2), -1.0))


def test_incompatible_units_raise_on_add():
    a = UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((2, 2)), unit="adu")
    b = UncertainImage(data=np.ones((2, 2)), uncertainty=np.ones((2, 2)), unit="electron")
    with pytest.raises(ValueError):
        a + b


def test_snr_is_signal_over_uncertainty():
    a = UncertainImage(data=np.array([[10.0, 0.0]]), uncertainty=np.array([[2.0, 0.0]]))
    snr = a.snr()
    assert snr[0, 0] == pytest.approx(5.0)
    assert np.isnan(snr[0, 1])
