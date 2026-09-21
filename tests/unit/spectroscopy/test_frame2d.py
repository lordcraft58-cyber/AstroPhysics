"""`frame2d.py`: máscara de calidad por píxel -- distinguir un 0 VÁLIDO
de un píxel realmente inválido, sin inventar defectos que los datos no
demuestran (ver docs/audit/55-... para el hallazgo real que motivó este
módulo)."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.frame2d import PixelFlag, SpectralFrame2D, build_pixel_mask, is_bad


def test_a_valid_zero_is_never_flagged_bad():
    """El caso central que motiva todo el módulo: un 0 (bias ya
    restado, cielo bajo) es un valor real, no un defecto."""
    data = np.array([[0.0, 1.0, 2.0], [3.0, 0.0, 5.0]])
    mask = build_pixel_mask(data)
    assert np.all(mask == PixelFlag.GOOD)
    assert not np.any(is_bad(mask, data.shape))


def test_nan_and_inf_are_always_flagged_with_no_configuration_needed():
    data = np.array([[1.0, np.nan, 3.0], [np.inf, -np.inf, 6.0]])
    mask = build_pixel_mask(data)
    assert mask[0, 1] & PixelFlag.NONFINITE
    assert mask[1, 0] & PixelFlag.NONFINITE
    assert mask[1, 1] & PixelFlag.NONFINITE
    assert mask[0, 0] == PixelFlag.GOOD
    assert mask[0, 2] == PixelFlag.GOOD


def test_saturation_is_inactive_without_a_real_saturate_value():
    """Sin `saturate_adu` real (p. ej. sin `SATURATE` en la cabecera,
    el caso de la cámara Atik del usuario), no se inventa un umbral."""
    data = np.array([[60000.0, 65535.0]])
    mask = build_pixel_mask(data)
    assert not np.any(mask & PixelFlag.SATURATED)


def test_saturation_flags_only_pixels_at_or_above_the_real_threshold():
    # margen del 0.1% (misma convención que detection.finder.enrich_detections):
    # 60000 * 0.999 = 59940.0
    data = np.array([[100.0, 59900.0, 60000.0, 70000.0]])
    mask = build_pixel_mask(data, saturate_adu=60000.0)
    assert not (mask[0, 0] & PixelFlag.SATURATED)
    assert not (mask[0, 1] & PixelFlag.SATURATED)
    assert mask[0, 2] & PixelFlag.SATURATED
    assert mask[0, 3] & PixelFlag.SATURATED


def test_dead_cosmic_ray_and_user_masks_never_inferred_only_supplied():
    data = np.zeros((2, 2))
    dead = np.array([[True, False], [False, False]])
    cosmic = np.array([[False, True], [False, False]])
    user = np.array([[False, False], [True, False]])

    mask = build_pixel_mask(data, dead_pixel_mask=dead, cosmic_ray_mask=cosmic, user_mask=user)
    assert mask[0, 0] & PixelFlag.DEAD
    assert mask[0, 1] & PixelFlag.COSMIC_RAY
    assert mask[1, 0] & PixelFlag.USER_MASKED
    assert mask[1, 1] == PixelFlag.GOOD  # nada supuesto donde no se aportó evidencia

    # sin ninguna máscara aportada, ninguno de estos motivos aparece jamás
    bare_mask = build_pixel_mask(data)
    assert np.all(bare_mask == PixelFlag.GOOD)


def test_a_pixel_can_combine_more_than_one_flag():
    data = np.array([[70000.0]])
    cosmic = np.array([[True]])
    mask = build_pixel_mask(data, saturate_adu=60000.0, cosmic_ray_mask=cosmic)
    assert mask[0, 0] & PixelFlag.SATURATED
    assert mask[0, 0] & PixelFlag.COSMIC_RAY


def test_mismatched_mask_shape_is_rejected_not_silently_broadcast():
    data = np.zeros((3, 3))
    with pytest.raises(ValueError):
        build_pixel_mask(data, dead_pixel_mask=np.zeros((2, 2), dtype=bool))


def test_is_bad_without_any_mask_treats_everything_as_good():
    """Una imagen sin máscara nunca se rechaza en silencio: se trata tal
    cual llegó."""
    assert not np.any(is_bad(None, (5, 5)))


def test_spectral_frame2d_rejects_mismatched_variance_or_mask_shape():
    data = np.zeros((4, 4))
    with pytest.raises(ValueError):
        SpectralFrame2D(data, variance=np.zeros((3, 3)))
    with pytest.raises(ValueError):
        SpectralFrame2D(data, mask=np.zeros((3, 3), dtype=np.uint16))


def test_spectral_frame2d_uncertainty_is_none_without_real_variance():
    frame = SpectralFrame2D(np.zeros((3, 3)))
    assert frame.uncertainty is None  # nunca un valor inventado


def test_spectral_frame2d_uncertainty_is_the_real_sqrt_of_variance():
    data = np.full((2, 2), 100.0)
    variance = np.full((2, 2), 25.0)
    frame = SpectralFrame2D(data, variance=variance)
    np.testing.assert_allclose(frame.uncertainty, 5.0)


def test_spectral_frame2d_is_bad_reflects_its_own_mask():
    data = np.zeros((2, 2))
    mask = build_pixel_mask(data, dead_pixel_mask=np.array([[True, False], [False, False]]))
    frame = SpectralFrame2D(data, mask=mask)
    assert frame.is_bad[0, 0]
    assert not frame.is_bad[0, 1]


def test_spectral_frame2d_rejects_non_2d_data():
    with pytest.raises(ValueError):
        SpectralFrame2D(np.zeros((2, 2, 2)))
