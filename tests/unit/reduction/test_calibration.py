from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.calibration import calibrate_frame
from astrophysics_suite.reduction.master_frames import MasterFrame


def _flat_frame(shape, level=1.0, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="flat")


def _bias_frame(shape, level, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="bias")


def _dark_frame(shape, level, exposure_s, uncertainty=0.0):
    return MasterFrame(data=np.full(shape, level), uncertainty=np.full(shape, uncertainty), n_combined=np.full(shape, 5), kind="dark", exposure_s=exposure_s)


def test_calibrate_frame_bias_only():
    shape = (4, 4)
    raw = np.full(shape, 1500.0)
    bias = _bias_frame(shape, 500.0)

    image, steps = calibrate_frame(raw, master_bias=bias)
    np.testing.assert_allclose(image.data, 1000.0)
    assert steps.bias_subtracted
    assert not steps.dark_subtracted
    assert not steps.flat_divided


def test_calibrate_frame_scales_dark_by_exposure_ratio():
    shape = (4, 4)
    raw = np.full(shape, 1000.0)
    dark = _dark_frame(shape, level=40.0, exposure_s=60.0)  # 40 ADU acumulados en 60s

    image, steps = calibrate_frame(raw, science_exposure_s=120.0, master_dark=dark)
    np.testing.assert_allclose(image.data, 1000.0 - 80.0)  # escalado x2 por el doble de exposición
    assert steps.dark_scale_factor == pytest.approx(2.0)


def test_calibrate_frame_requires_exposure_for_dark():
    shape = (4, 4)
    dark = _dark_frame(shape, level=40.0, exposure_s=60.0)
    with pytest.raises(ValueError):
        calibrate_frame(np.full(shape, 1000.0), master_dark=dark)


def test_calibrate_frame_divides_by_flat():
    shape = (4, 4)
    raw = np.full(shape, 1000.0)
    flat = _flat_frame(shape, level=0.5)

    image, steps = calibrate_frame(raw, master_flat=flat)
    np.testing.assert_allclose(image.data, 2000.0)
    assert steps.flat_divided


def test_calibrate_frame_full_chain_matches_manual_arithmetic():
    shape = (4, 4)
    raw = np.full(shape, 2000.0)
    bias = _bias_frame(shape, 500.0)
    dark = _dark_frame(shape, level=30.0, exposure_s=30.0)
    flat = _flat_frame(shape, level=0.8)

    image, steps = calibrate_frame(raw, science_exposure_s=30.0, master_bias=bias, master_dark=dark, master_flat=flat)
    expected = ((2000.0 - 500.0) - 30.0) / 0.8
    np.testing.assert_allclose(image.data, expected)
    assert steps.bias_subtracted and steps.dark_subtracted and steps.flat_divided


def test_calibrate_frame_interpolates_bad_pixels():
    shape = (3, 6)
    raw = np.full(shape, 1000.0)
    raw[1, 3] = 999999.0  # píxel defectuoso conocido
    mask = np.zeros(shape, dtype=bool)
    mask[1, 3] = True

    image, steps = calibrate_frame(raw, bad_pixel_mask=mask)
    assert image.data[1, 3] == pytest.approx(1000.0)
    assert steps.bad_pixels_interpolated
