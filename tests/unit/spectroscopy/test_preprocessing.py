"""`preprocessing.py`: RAW -> BIAS -> DARK -> FLAT -> BAD PIXEL MASK ->
COSMIC RAY CLEANING -> 2D SCIENCE (§7), sobre motores ya probados --
nunca sustituye un valor de rayo cósmico en silencio (§6: la
interpolación es opcional)."""
from __future__ import annotations

import numpy as np

from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.spectroscopy.frame2d import PixelFlag
from astrophysics_suite.spectroscopy.preprocessing import preprocess_spectroscopic_frame
from astrophysics_suite.spectroscopy.synthetic_lamp import generate_synthetic_lamp_frame2d


def _master(kind: str, value: float, shape=(60, 1600)):
    return MasterFrame(
        kind=kind, data=np.full(shape, value, dtype=np.float64),
        uncertainty=np.full(shape, 0.5), n_combined=np.full(shape, 5, dtype=np.int64),
        exposure_s=60.0 if kind == "dark" else None,
    )


def _frame_with_cosmic_rays(n_cosmic_rays=5, seed=3):
    return generate_synthetic_lamp_frame2d(
        "Ne", shape=(60, 1600), curvature_px=2.0, seed=seed,
        wavelength_at_pixel0=5700.0, dispersion_angstrom_per_px=1.4,
        n_cosmic_rays=n_cosmic_rays, cosmic_ray_amplitude=50000.0,
    )


def test_cosmic_rays_are_flagged_at_their_real_injected_positions():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=6, seed=11)
    result = preprocess_spectroscopic_frame(frame.data, gain_e_per_adu=1.0, read_noise_e=5.0)
    assert result.n_cosmic_rays_flagged >= 6
    for row, col in frame.cosmic_ray_pixels:
        assert result.frame.mask[row, col] & PixelFlag.COSMIC_RAY


def test_cosmic_rays_are_never_interpolated_by_default():
    """§6: la interpolación es opcional -- por defecto, el valor
    original (inflado) se conserva, solo se marca."""
    frame = _frame_with_cosmic_rays(n_cosmic_rays=3, seed=5)
    result = preprocess_spectroscopic_frame(frame.data, gain_e_per_adu=1.0, read_noise_e=5.0)
    assert not result.cosmic_ray_interpolation_applied
    for row, col in frame.cosmic_ray_pixels:
        assert result.frame.data[row, col] == frame.data[row, col]


def test_cosmic_ray_interpolation_can_be_opted_into_explicitly():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=3, seed=5)
    result = preprocess_spectroscopic_frame(
        frame.data, gain_e_per_adu=1.0, read_noise_e=5.0, apply_cosmic_ray_interpolation=True,
    )
    assert result.cosmic_ray_interpolation_applied
    for row, col in frame.cosmic_ray_pixels:
        # el valor inflado por el rayo cosmico ya no esta ahi
        assert result.frame.data[row, col] != frame.data[row, col]
        # y sigue marcado: interpolar no borra la sospecha
        assert result.frame.mask[row, col] & PixelFlag.COSMIC_RAY


def test_cosmic_ray_detection_can_be_disabled_and_reports_zero_honestly():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=4, seed=7)
    result = preprocess_spectroscopic_frame(frame.data, gain_e_per_adu=1.0, read_noise_e=5.0, detect_cosmic_rays_enabled=False)
    assert result.n_cosmic_rays_flagged == 0
    for row, col in frame.cosmic_ray_pixels:
        assert not (result.frame.mask[row, col] & PixelFlag.COSMIC_RAY)


def test_bias_and_flat_masters_are_really_applied():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=0)
    bias = _master("bias", 500.0)
    flat = _master("flat", 1.0)
    result = preprocess_spectroscopic_frame(frame.data, master_bias=bias, master_flat=flat, gain_e_per_adu=1.0)
    assert result.calibration_steps.bias_subtracted
    assert result.calibration_steps.flat_divided
    assert not result.calibration_steps.dark_subtracted
    # el bias real se resto de verdad
    np.testing.assert_allclose(result.frame.data.mean(), frame.data.mean() - 500.0, atol=5.0)


def test_variance_is_propagated_not_invented():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=0)
    result = preprocess_spectroscopic_frame(frame.data, gain_e_per_adu=2.0, read_noise_e=4.0)
    assert result.frame.variance is not None
    assert np.all(result.frame.variance > 0)
    np.testing.assert_allclose(result.frame.uncertainty, np.sqrt(result.frame.variance))


def test_saturation_is_flagged_only_with_a_real_saturate_value():
    frame = _frame_with_cosmic_rays(n_cosmic_rays=0)
    data = frame.data.copy()
    data[10, 800] = 65000.0
    result_without = preprocess_spectroscopic_frame(data, gain_e_per_adu=1.0)
    assert not np.any(result_without.frame.mask & PixelFlag.SATURATED)

    result_with = preprocess_spectroscopic_frame(data, gain_e_per_adu=1.0, saturate_adu=60000.0)
    assert result_with.frame.mask[10, 800] & PixelFlag.SATURATED
