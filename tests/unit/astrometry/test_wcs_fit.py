from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.astrometry.wcs_fit import (
    angular_separation_deg,
    fit_wcs,
    gnomonic_deproject,
    gnomonic_project,
    wcs_solution_from_astropy,
    wcs_solution_to_astropy,
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


def test_wcs_solution_from_astropy_matches_direct_pix2world():
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [500.5, 400.5]  # convención FITS 1-indexada
    wcs.wcs.cdelt = [-0.4 / 3600.0, 0.4 / 3600.0]
    wcs.wcs.crval = [210.0, -15.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    solution = wcs_solution_from_astropy(wcs)

    assert solution.crval_deg == pytest.approx((210.0, -15.0))
    assert solution.crpix_px == pytest.approx((499.5, 399.5))  # convertido a 0-indexada
    assert solution.n_stars == 0
    assert solution.rms_residual_arcsec == pytest.approx(0.0)

    for x0, y0 in [(499.5, 399.5), (300.0, 250.0), (700.0, 600.0)]:
        expected_ra, expected_dec = wcs.celestial.all_pix2world(x0, y0, 0)
        ra, dec = solution.pixel_to_sky(x0, y0)
        assert ra == pytest.approx(float(expected_ra), abs=1e-6)
        assert dec == pytest.approx(float(expected_dec), abs=1e-6)


def test_wcs_solution_to_astropy_round_trips_through_wcs_solution_from_astropy():
    """Inversa real de `wcs_solution_from_astropy`: un `WCSSolution` real
    (de `fit_wcs`, no inventado) debe sobrevivir la conversión a
    `astropy.wcs.WCS` y de vuelta sin perder precisión -- la forma en que
    una solución resuelta en el taller (manual o `plate_solve`) se
    guarda en un FITS real y se recupera al reabrirlo."""
    rng = np.random.default_rng(3)
    crpix_px = (256.0, 256.0)
    n = 12
    xs = rng.uniform(50, 460, n)
    ys = rng.uniform(50, 460, n)
    true_ra0, true_dec0 = 187.3, -5.7
    true_cd = np.array([[-0.28 / 3600.0, 0.03 / 3600.0], [0.03 / 3600.0, 0.28 / 3600.0]])
    dx, dy = xs - crpix_px[0], ys - crpix_px[1]
    xi, eta = true_cd @ np.vstack([dx, dy])
    ra, dec = gnomonic_deproject(xi, eta, true_ra0, true_dec0)

    solution = fit_wcs(list(zip(xs, ys)), list(zip(ra, dec)), crpix_px=crpix_px)

    astropy_wcs = wcs_solution_to_astropy(solution)
    round_tripped = wcs_solution_from_astropy(astropy_wcs)

    assert round_tripped.crval_deg == pytest.approx(solution.crval_deg, abs=1e-9)
    assert round_tripped.crpix_px == pytest.approx(solution.crpix_px, abs=1e-6)
    np.testing.assert_allclose(round_tripped.cd_matrix_deg_per_px, solution.cd_matrix_deg_per_px, atol=1e-12)

    for x0, y0 in [(100.0, 120.0), (400.0, 300.0)]:
        original_ra, original_dec = solution.pixel_to_sky(x0, y0)
        restored_ra, restored_dec = round_tripped.pixel_to_sky(x0, y0)
        assert restored_ra == pytest.approx(original_ra, abs=1e-8)
        assert restored_dec == pytest.approx(original_dec, abs=1e-8)


def test_wcs_solution_to_astropy_writes_a_real_fits_header(tmp_path):
    """El propósito real de la conversión: producir un header FITS que un
    lector externo (astropy) interprete como el WCS correcto -- no solo
    que los números del objeto Python coincidan."""
    from astropy.io import fits
    from astropy.wcs import WCS as AstropyWCS

    solution = fit_wcs(
        [(10.0, 10.0), (90.0, 10.0), (10.0, 90.0), (90.0, 90.0)],
        [(100.01, 30.0), (99.99, 30.0), (100.01, 30.02), (99.99, 30.02)],
        crpix_px=(50.0, 50.0),
    )

    astropy_wcs = wcs_solution_to_astropy(solution)
    header = astropy_wcs.to_header()

    path = tmp_path / "solved.fits"
    fits.PrimaryHDU(data=np.zeros((100, 100), dtype=np.float32), header=header).writeto(path)

    with fits.open(path) as hdul:
        reloaded_wcs = AstropyWCS(hdul[0].header)
        assert reloaded_wcs.has_celestial
        for x0, y0 in [(50.0, 50.0), (10.0, 10.0)]:
            expected_ra, expected_dec = solution.pixel_to_sky(x0, y0)
            got_ra, got_dec = reloaded_wcs.all_pix2world(x0, y0, 0)
            assert float(got_ra) == pytest.approx(expected_ra, abs=1e-6)
            assert float(got_dec) == pytest.approx(expected_dec, abs=1e-6)


def test_wcs_solution_from_astropy_accepts_explicit_crpix():
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [100.0, 100.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [10.0, 5.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    solution = wcs_solution_from_astropy(wcs, crpix_px=(50.0, 60.0))

    assert solution.crpix_px == (50.0, 60.0)


def test_rescale_wcs_for_binning_matches_the_real_superpixel_centre():
    """El demosaico SuperPixel (`imtools/debayer.py`) binifica 2x2: el
    píxel de salida (i,j) cubre los de entrada (2i,2j)..(2i+1,2j+1), cuyo
    centro está en (2j+0.5, 2i+0.5). El WCS reescalado debe dar
    exactamente esa posición celeste.

    No se puede usar `wcs[::2, ::2]` de astropy para esto: con matriz CD
    (lo normal en un FITS ya resuelto) deja la escala SIN cambiar -- con
    un light real de M 31 eso daba un error de ~857 segundos de arco."""
    from astropy.wcs import WCS

    from astrophysics_suite.astrometry.wcs_fit import rescale_wcs_for_binning

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [512.0, 400.0]
    wcs.wcs.crval = [10.9131301993, 41.2120838282]
    wcs.wcs.cd = [[0.000245450853875, 0.000149121982691], [-0.00014909406634, 0.000245457021999]]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    binned = rescale_wcs_for_binning(wcs, 2)

    original_scale = np.sqrt(abs(np.linalg.det(wcs.pixel_scale_matrix)))
    binned_scale = np.sqrt(abs(np.linalg.det(binned.pixel_scale_matrix)))
    assert binned_scale == pytest.approx(original_scale * 2.0, rel=1e-9), "la escala de píxel debe DOBLARSE al binificar 2x2"

    for i, j in [(10, 10), (200, 150), (400, 380)]:
        expected_ra, expected_dec = wcs.all_pix2world(2 * j + 0.5, 2 * i + 0.5, 0)
        got_ra, got_dec = binned.all_pix2world(j, i, 0)
        assert float(got_ra) == pytest.approx(float(expected_ra), abs=1e-9)
        assert float(got_dec) == pytest.approx(float(expected_dec), abs=1e-9)


def test_rescale_wcs_for_binning_leaves_the_original_untouched():
    from astropy.wcs import WCS

    from astrophysics_suite.astrometry.wcs_fit import rescale_wcs_for_binning

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [100.0, 100.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [10.0, 5.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    original_crpix = list(wcs.wcs.crpix)

    rescale_wcs_for_binning(wcs, 2)

    assert list(wcs.wcs.crpix) == original_crpix, "reescalar nunca debe mutar el WCS de entrada"
