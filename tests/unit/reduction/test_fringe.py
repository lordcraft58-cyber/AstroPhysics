from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.fringe import remove_fringe


def test_remove_fringe_recovers_known_scale_factor():
    rng = np.random.default_rng(5)
    shape = (30, 30)
    pattern = rng.normal(0, 1.0, shape)  # patrón de franjas de referencia (zero-mean)
    true_scale = 2.3
    sky_background = 500.0
    data = sky_background + true_scale * pattern

    result = remove_fringe(data, pattern)
    assert result.scale_factor == pytest.approx(true_scale, rel=1e-6)
    np.testing.assert_allclose(result.data, sky_background, atol=1e-6)


def test_remove_fringe_preserves_background_level():
    shape = (10, 10)
    pattern = np.zeros(shape)
    pattern[3:7, 3:7] = 5.0
    data = np.full(shape, 300.0) + pattern

    result = remove_fringe(data, pattern)
    assert abs(np.mean(result.data) - 300.0) < 1.0


def test_remove_fringe_shape_mismatch_raises():
    with pytest.raises(ValueError):
        remove_fringe(np.zeros((3, 3)), np.zeros((4, 4)))


def test_remove_fringe_constant_pattern_raises():
    with pytest.raises(ValueError):
        remove_fringe(np.ones((3, 3)), np.full((3, 3), 5.0))


def test_remove_fringe_respects_fit_region():
    # patrón con variación espacial real (como unas franjas de verdad),
    # igual en ambas mitades -- pero solo la mitad superior de `data`
    # contiene esa señal a escala 3.0; la mitad inferior no tiene ninguna
    # componente de franjas, aunque el patrón candidato sigue "existiendo"
    # ahí. Si `fit_region` no restringiera el ajuste correctamente, la
    # mitad inferior (sin señal) sesgaría el factor de escala hacia abajo.
    shape = (20, 20)
    columns = np.arange(shape[1])
    row_pattern = np.sin(2 * np.pi * columns / 6.0)
    pattern = np.tile(row_pattern, (shape[0], 1))

    data = np.full(shape, 100.0)
    data[:10, :] += 3.0 * pattern[:10, :]
    fit_region = (slice(0, 10), slice(None))

    result = remove_fringe(data, pattern, fit_region=fit_region)
    assert result.scale_factor == pytest.approx(3.0, abs=1e-6)
