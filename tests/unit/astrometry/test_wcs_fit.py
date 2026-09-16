from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.astrometry.wcs_fit import (
    angular_separation_deg,
    fit_wcs,
    gnomonic_deproject,
    gnomonic_project,
)


def test_gnomonic_deproject_at_origin_returns_reference_point():
    ra, dec = gnomonic_deproject(np.array([0.0]), np.array([0.0]), 150.0, 20.0)
    assert ra[0] == pytest.approx(150.0)
    assert dec[0] == pytest.approx(20.0)


def test_gnomonic_round_trip_recovers_original_coordinates():
    rng = np.random.default_rng(0)
    ra0, dec0 = 200.0, -10.0
    ra = ra0 + rng.uniform(-0.3, 0.3, 50)
    dec = dec0 + rng.uniform(-0.3, 0.3, 50)

    xi, eta = gnomonic_project(ra, dec, ra0, dec0)
    ra_back, dec_back = gnomonic_deproject(xi, eta, ra0, dec0)

    np.testing.assert_allclose(ra_back, ra, atol=1e-9)
    np.testing.assert_allclose(dec_back, dec, atol=1e-9)


def test_angular_separation_matches_known_cases():
    assert angular_separation_deg(10.0, 20.0, 10.0, 20.0) == pytest.approx(0.0, abs=1e-12)
    assert angular_separation_deg(0.0, 0.0, 0.0, 1.0) == pytest.approx(1.0, abs=1e-9)
    assert angular_separation_deg(0.0, 0.0, 1.0, 0.0) == pytest.approx(1.0, abs=1e-9)


def _synthetic_wcs_stars(n=12, seed=1):
    crval = (150.0, 20.0)
    crpix = (512.0, 512.0)
    scale = 0.4 / 3600.0  # 0.4"/px en grados
    theta = math.radians(7.0)
    cd_matrix = scale * np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])

    rng = np.random.default_rng(seed)
    xs = rng.uniform(0, 1024, n)
    ys = rng.uniform(0, 1024, n)
    dx, dy = xs - crpix[0], ys - crpix[1]
    xi_eta = cd_matrix @ np.vstack([dx, dy])
    ras, decs = gnomonic_deproject(xi_eta[0], xi_eta[1], crval[0], crval[1])
    pixel_xy = list(zip(xs, ys))
    sky_radec = list(zip(ras, decs))
    return pixel_xy, sky_radec, crval, crpix, cd_matrix


def test_fit_wcs_recovers_known_solution_noiselessly():
    pixel_xy, sky_radec, true_crval, true_crpix, true_cd = _synthetic_wcs_stars()

    solution = fit_wcs(pixel_xy, sky_radec, crpix_px=true_crpix)

    assert solution.crval_deg[0] == pytest.approx(true_crval[0], abs=1e-8)
    assert solution.crval_deg[1] == pytest.approx(true_crval[1], abs=1e-8)
    np.testing.assert_allclose(solution.cd_matrix_deg_per_px, true_cd, atol=1e-12)
    assert solution.rms_residual_arcsec < 1e-4  # precisión de punto flotante, no ruido real


def test_fit_wcs_pixel_to_sky_and_back_round_trips():
    pixel_xy, sky_radec, _, true_crpix, _ = _synthetic_wcs_stars()
    solution = fit_wcs(pixel_xy, sky_radec, crpix_px=true_crpix)

    x0, y0 = 300.0, 700.0
    ra, dec = solution.pixel_to_sky(x0, y0)
    x_back, y_back = solution.sky_to_pixel(ra, dec)
    assert x_back == pytest.approx(x0, abs=1e-6)
    assert y_back == pytest.approx(y0, abs=1e-6)


def test_fit_wcs_requires_at_least_three_stars():
    with pytest.raises(ValueError):
        fit_wcs([(0, 0), (1, 1)], [(150.0, 20.0), (150.1, 20.1)], crpix_px=(0, 0))


def test_fit_wcs_rejects_length_mismatch():
    with pytest.raises(ValueError):
        fit_wcs([(0, 0), (1, 1), (2, 2)], [(150.0, 20.0), (150.1, 20.1)], crpix_px=(0, 0))
