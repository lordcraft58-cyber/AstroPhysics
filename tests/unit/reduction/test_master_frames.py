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


def test_save_and_load_master_frame_round_trips_data_uncertainty_and_n_combined(tmp_path):
    """El guardado no debe perder la incertidumbre real ni el nº de
    fotogramas combinados -- `calibration.py` propaga esa incertidumbre
    de verdad al aplicar la calibración, así que inventarla al releer
    (p. ej. con ceros) falsearía la propagación de errores."""
    from astrophysics_suite.reduction.master_frames import load_master_frame, save_master_frame

    rng = np.random.default_rng(4)
    bias_frames = [np.full((5, 5), 500.0) + rng.normal(0, 3.0, (5, 5)) for _ in range(5)]
    master = build_master_bias(bias_frames)
    assert np.any(master.uncertainty > 0)

    path = tmp_path / "masters" / "master_bias_test.fits"
    save_master_frame(str(path), master)
    assert path.exists()

    reloaded = load_master_frame(str(path))
    assert reloaded.kind == "bias"
    np.testing.assert_allclose(reloaded.data, master.data, atol=1e-3)
    np.testing.assert_allclose(reloaded.uncertainty, master.uncertainty, atol=1e-3)
    np.testing.assert_array_equal(reloaded.n_combined, master.n_combined)


def test_save_and_load_master_dark_preserves_exposure(tmp_path):
    from astrophysics_suite.reduction.master_frames import load_master_frame, save_master_frame

    dark_frames = [np.full((4, 4), 520.0) for _ in range(4)]
    master = build_master_dark(dark_frames, exposure_s=120.0)

    path = tmp_path / "master_dark_test.fits"
    save_master_frame(str(path), master)
    reloaded = load_master_frame(str(path))

    assert reloaded.kind == "dark"
    assert reloaded.exposure_s == pytest.approx(120.0)


def test_load_master_frame_rejects_a_fits_that_is_not_a_saved_master_frame(tmp_path):
    """Nunca debe aceptar un FITS cualquiera y rellenar incertidumbre/nº
    de fotogramas inventados -- si no tiene la forma real que escribe
    `save_master_frame`, se rechaza con un motivo explícito."""
    from astropy.io import fits

    from astrophysics_suite.reduction.master_frames import load_master_frame

    path = tmp_path / "not_a_master.fits"
    fits.PrimaryHDU(data=np.zeros((4, 4), dtype=np.float32)).writeto(path)

    with pytest.raises(ValueError, match="MASTKIND"):
        load_master_frame(str(path))


def test_save_master_frame_confirms_overwrite_is_the_callers_responsibility(tmp_path):
    """`save_master_frame` en sí escribe siempre que `overwrite=True`
    (por defecto) -- la confirmación de sobrescritura ante el usuario es
    responsabilidad de la GUI (`BuildMasterFrameDialog`), no de esta
    función de bajo nivel; con `overwrite=False` debe fallar si ya existe."""
    from astropy.io import fits

    from astrophysics_suite.reduction.master_frames import save_master_frame

    path = tmp_path / "existing.fits"
    fits.PrimaryHDU(data=np.zeros((3, 3), dtype=np.float32)).writeto(path)

    master = build_master_bias([np.full((3, 3), 100.0) for _ in range(3)])
    with pytest.raises(OSError):
        save_master_frame(str(path), master, overwrite=False)
