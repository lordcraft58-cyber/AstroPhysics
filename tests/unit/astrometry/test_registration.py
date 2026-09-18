from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.astrometry.registration import (
    apply_affine_transform,
    fit_affine_transform,
    reproject_to_reference,
)
from astrophysics_suite.astrometry.wcs_fit import fit_wcs, gnomonic_deproject


def test_fit_affine_transform_recovers_known_rotation_and_translation():
    theta = math.radians(3.0)
    true_matrix = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    true_offset = np.array([15.0, -8.0])

    rng = np.random.default_rng(2)
    reference_points = rng.uniform(0, 500, (10, 2))
    target_points = [tuple(true_matrix @ p + true_offset) for p in reference_points]

    transform = fit_affine_transform(list(map(tuple, reference_points)), target_points)
    np.testing.assert_allclose(transform.matrix, true_matrix, atol=1e-9)
    np.testing.assert_allclose(transform.offset, true_offset, atol=1e-7)
    assert transform.rms_residual_px < 1e-6


def test_fit_affine_transform_similarity_model():
    scale = 1.5
    theta = math.radians(10.0)
    a, b = scale * math.cos(theta), scale * math.sin(theta)
    true_matrix = np.array([[a, -b], [b, a]])
    true_offset = np.array([3.0, 4.0])

    rng = np.random.default_rng(4)
    reference_points = rng.uniform(0, 200, (8, 2))
    target_points = [tuple(true_matrix @ p + true_offset) for p in reference_points]

    transform = fit_affine_transform(list(map(tuple, reference_points)), target_points, model="similarity")
    np.testing.assert_allclose(transform.matrix, true_matrix, atol=1e-8)
    np.testing.assert_allclose(transform.offset, true_offset, atol=1e-6)


def test_fit_affine_transform_requires_at_least_three_points():
    with pytest.raises(ValueError):
        fit_affine_transform([(0, 0), (1, 1)], [(0, 0), (1, 1)])


def test_fit_affine_transform_rejects_length_mismatch():
    with pytest.raises(ValueError):
        fit_affine_transform([(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1)])


def test_fit_affine_transform_rejects_invalid_model():
    with pytest.raises(ValueError):
        fit_affine_transform([(0, 0), (1, 1), (2, 2)], [(0, 0), (1, 1), (2, 2)], model="projective")


def test_apply_affine_transform_translates_point_source():
    shape = (40, 40)
    data = np.zeros(shape)
    data[20, 15] = 1000.0  # (fila=y, columna=x) -> x=15, y=20

    identity_rotation = np.eye(2)
    translation = np.array([5.0, 0.0])  # +5 en x
    from astrophysics_suite.astrometry.registration import AffineTransform

    transform = AffineTransform(matrix=identity_rotation, offset=translation, rms_residual_px=0.0, n_points=3)
    result = apply_affine_transform(data, transform, order=0)

    assert result[20, 20] == pytest.approx(1000.0)


def test_reproject_to_reference_recovers_same_grid_for_identical_wcs():
    crval = (150.0, 20.0)
    crpix = (25.0, 25.0)
    scale = 1.0 / 3600.0
    cd_matrix = scale * np.eye(2)

    shape = (50, 50)
    yy, xx = np.mgrid[0:50, 0:50]
    data = np.exp(-(((xx - 25) ** 2 + (yy - 25) ** 2)) / (2 * 3.0**2)) * 1000.0

    # dos "soluciones" idénticas -- reproyectar sobre sí misma debe ser la identidad
    dx, dy = (xx.astype(float) - crpix[0]).ravel(), (yy.astype(float) - crpix[1]).ravel()
    xi_eta = cd_matrix @ np.vstack([dx, dy])
    ras, decs = gnomonic_deproject(xi_eta[0], xi_eta[1], crval[0], crval[1])
    pixel_xy = list(zip(xx.ravel().astype(float), yy.ravel().astype(float)))
    sky_radec = list(zip(ras, decs))

    # usa solo un subconjunto disperso de puntos para el ajuste (rápido y suficiente)
    idx = np.linspace(0, len(pixel_xy) - 1, 30, dtype=int)
    solution = fit_wcs([pixel_xy[i] for i in idx], [sky_radec[i] for i in idx], crpix_px=crpix)

    reprojected = reproject_to_reference(data, solution, solution, output_shape=shape, order=1)
    np.testing.assert_allclose(reprojected, data, atol=1.0)
