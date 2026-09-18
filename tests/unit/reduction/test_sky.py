from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.reduction.sky import fit_sky_background, subtract_sky_background


def _linear_sky(shape, base=100.0, slope_x=20.0, slope_y=10.0):
    height, width = shape
    yy, xx = np.mgrid[0:height, 0:width]
    x = xx / (width - 1)
    y = yy / (height - 1)
    return base + slope_x * x + slope_y * y


def test_fit_sky_background_recovers_linear_gradient_and_rejects_stars():
    shape = (50, 60)
    sky = _linear_sky(shape)
    data = sky.copy()

    star_positions = [(10, 15), (30, 45), (40, 20)]
    for y, x in star_positions:
        yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
        data = data + 2000.0 * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2)) / (2 * 2.0**2))

    fit = fit_sky_background(data, degree=1, sigma_clip=3.0)

    # el modelo debe recuperar el gradiente de verdad, lejos de las estrellas
    background_only = np.ones(shape, dtype=bool)
    for y, x in star_positions:
        background_only[max(0, y - 5):y + 5, max(0, x - 5):x + 5] = False
    np.testing.assert_allclose(fit.model[background_only], sky[background_only], atol=2.0)

    for y, x in star_positions:
        assert fit.source_mask[y, x]  # el centro de cada estrella se marcó como fuente


def test_subtract_sky_background_flattens_gradient_leaving_stars():
    shape = (40, 40)
    sky = _linear_sky(shape, base=200.0, slope_x=50.0, slope_y=0.0)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    star = 5000.0 * np.exp(-(((xx - 20) ** 2 + (yy - 20) ** 2)) / (2 * 2.0**2))
    data = sky + star

    fit = fit_sky_background(data, degree=1)
    corrected = subtract_sky_background(data, fit)

    background_only = corrected.copy()
    background_only[15:26, 15:26] = np.nan
    residual_std = np.nanstd(background_only)
    assert residual_std < 6.0  # el fondo queda plano, sin el gradiente de 50 ADU de borde a borde
    assert corrected[20, 20] > 4000.0  # la estrella sigue ahí, muy por encima del fondo


def test_fit_sky_background_constant_degree_zero_matches_robust_level():
    shape = (20, 20)
    data = np.full(shape, 150.0)
    data[10, 10] = 9000.0  # fuente puntual aislada

    fit = fit_sky_background(data, degree=0, sigma_clip=3.0)

    np.testing.assert_allclose(fit.model, 150.0, atol=1.0)
    assert fit.source_mask[10, 10]


def test_fit_sky_background_rejects_negative_degree():
    with pytest.raises(ValueError):
        fit_sky_background(np.ones((10, 10)), degree=-1)


def test_subtract_sky_background_rejects_shape_mismatch():
    fit = fit_sky_background(np.ones((10, 10)), degree=0)
    with pytest.raises(ValueError):
        subtract_sky_background(np.ones((5, 5)), fit)
