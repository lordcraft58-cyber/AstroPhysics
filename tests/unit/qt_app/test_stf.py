"""Matemática pura del STF -- sin Qt, comprobable sin display."""
from __future__ import annotations

import numpy as np
import pytest

from qt_app.mdi.stf import (
    STFParams,
    apply_stf,
    compute_stf_params,
    midtones_transfer_function,
    stf_to_uint8,
)


def test_mtf_endpoints_are_fixed_regardless_of_m():
    for m in (0.1, 0.25, 0.5, 0.75, 0.9):
        assert midtones_transfer_function(0.0, m) == pytest.approx(0.0)
        assert midtones_transfer_function(1.0, m) == pytest.approx(1.0)


def test_mtf_at_m_equals_half():
    # la identidad que define "m" (balance de tonos medios): el nivel de
    # entrada m es justo el que se transforma en el gris medio (0.5) de
    # salida -- no al revés (MTF(0.5) no es, en general, igual a m).
    for m in (0.1, 0.3, 0.5, 0.7, 0.9):
        assert midtones_transfer_function(m, m) == pytest.approx(0.5, abs=1e-9)


def test_mtf_clips_outside_unit_range():
    assert midtones_transfer_function(-0.5, 0.3) == pytest.approx(0.0)
    assert midtones_transfer_function(1.5, 0.3) == pytest.approx(1.0)


def test_compute_stf_params_maps_median_to_target_background():
    rng = np.random.default_rng(0)
    data = rng.normal(1000.0, 50.0, (100, 100))
    target = 0.25

    params = compute_stf_params(data, target_background=target)
    median = float(np.median(data))
    stretched_median = float(apply_stf(np.array([median]), params)[0])
    assert stretched_median == pytest.approx(target, abs=1e-4)


def test_compute_stf_params_maps_max_to_near_one():
    rng = np.random.default_rng(1)
    data = rng.normal(500.0, 20.0, (50, 50))
    params = compute_stf_params(data)
    stretched_max = float(apply_stf(np.array([np.max(data)]), params)[0])
    assert stretched_max == pytest.approx(1.0, abs=1e-6)


def test_compute_stf_params_rejects_all_nan():
    with pytest.raises(ValueError):
        compute_stf_params(np.full((5, 5), np.nan))


def test_apply_stf_never_mutates_input_array():
    data = np.array([[1.0, 2.0], [3.0, 4.0]])
    original = data.copy()
    params = compute_stf_params(data)
    apply_stf(data, params)
    np.testing.assert_array_equal(data, original)


def test_stf_to_uint8_has_correct_dtype_and_range():
    rng = np.random.default_rng(2)
    data = rng.normal(2000.0, 300.0, (30, 30))
    params = compute_stf_params(data)
    image = stf_to_uint8(data, params)
    assert image.dtype == np.uint8
    assert image.min() >= 0 and image.max() <= 255


def test_apply_stf_is_invariant_to_affine_rescaling_of_data():
    """El estiramiento se deriva de la estadística de la propia imagen
    (mediana/MAD), así que una imagen re-escalada linealmente (distinta
    ganancia/offset, misma forma de distribución) debe producir
    virtualmente el mismo resultado visual tras recalcular sus propios
    parámetros -- la propiedad central de un "auto"-stretch."""
    rng = np.random.default_rng(3)
    base = rng.normal(1000.0, 80.0, (60, 60))
    rescaled = base * 3.5 + 200.0

    params_base = compute_stf_params(base)
    params_rescaled = compute_stf_params(rescaled)

    stretched_base = apply_stf(base, params_base)
    stretched_rescaled = apply_stf(rescaled, params_rescaled)
    np.testing.assert_allclose(stretched_base, stretched_rescaled, atol=1e-6)


def test_compute_stf_params_constant_image_does_not_raise():
    data = np.full((10, 10), 500.0)
    params = compute_stf_params(data)
    assert isinstance(params, STFParams)
    result = apply_stf(data, params)
    assert np.all(np.isfinite(result))
