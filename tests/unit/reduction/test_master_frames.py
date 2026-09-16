from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.master_frames import build_master_bias, build_master_dark, build_master_flat


def test_build_master_bias_combines_and_rejects_outlier():
    rng = np.random.default_rng(2)
    bias_level = 1000.0
    frames = [np.full((6, 6), bias_level) + rng.normal(0, 2.0, (6, 6)) for _ in range(6)]
    frames[3][2, 2] = 50000.0  # rayo cósmico en un fotograma de bias

    master = build_master_bias(frames)
    assert master.kind == "bias"
    assert master.data[2, 2] == pytest.approx(bias_level, abs=10.0)


def test_build_master_bias_requires_at_least_three_frames():
    with pytest.raises(ValueError):
        build_master_bias([np.zeros((3, 3)), np.zeros((3, 3))])


def test_build_master_dark_subtracts_bias_and_records_exposure():
    bias_frames = [np.full((4, 4), 500.0) for _ in range(3)]
    master_bias = build_master_bias(bias_frames)

    dark_level_above_bias = 20.0
    dark_frames = [np.full((4, 4), 500.0 + dark_level_above_bias) for _ in range(3)]
    master_dark = build_master_dark(dark_frames, exposure_s=60.0, master_bias=master_bias.data)

    np.testing.assert_allclose(master_dark.data, dark_level_above_bias, atol=1e-6)
    assert master_dark.exposure_s == 60.0
    assert master_dark.kind == "dark"


def test_build_master_dark_rejects_non_positive_exposure():
    with pytest.raises(ValueError):
        build_master_dark([np.zeros((3, 3))] * 3, exposure_s=0.0)


def test_build_master_flat_normalizes_to_unit_median():
    flat_frames = [np.full((5, 5), 40000.0) for _ in range(4)]
    # introduce una variación de sensibilidad real: una esquina más tenue
    for frame in flat_frames:
        frame[0:2, 0:2] *= 0.8

    master = build_master_flat(flat_frames)
    assert master.kind == "flat"
    assert np.median(master.data) == pytest.approx(1.0, abs=1e-6)
    assert master.data[0, 0] == pytest.approx(0.8, abs=1e-3)


def test_build_master_flat_with_dark_requires_flat_exposure():
    from astrophysics_suite.reduction.master_frames import MasterFrame

    fake_dark = MasterFrame(data=np.zeros((3, 3)), uncertainty=np.zeros((3, 3)), n_combined=np.full((3, 3), 3), kind="dark", exposure_s=30.0)
    with pytest.raises(ValueError):
        build_master_flat([np.full((3, 3), 1000.0)] * 3, master_dark=fake_dark)


def test_build_master_flat_rejects_non_positive_median():
    with pytest.raises(ValueError):
        build_master_flat([np.zeros((3, 3))] * 3)
