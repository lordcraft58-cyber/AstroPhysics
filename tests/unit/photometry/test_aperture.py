from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.photometry.aperture import (
    aperture_coverage_mask,
    aperture_photometry,
    estimate_local_sky,
    fit_curve_of_growth,
)


def test_coverage_mask_total_area_matches_circle_area():
    shape = (41, 41)
    radius = 10.0
    mask = aperture_coverage_mask(shape, 20.0, 20.0, radius, oversample=10)
    np.testing.assert_allclose(np.sum(mask), math.pi * radius**2, rtol=0.01)


def test_coverage_mask_center_pixel_fully_covered_for_large_radius():
    mask = aperture_coverage_mask((21, 21), 10.0, 10.0, 8.0)
    assert mask[10, 10] == pytest.approx(1.0)


def test_coverage_mask_rejects_non_positive_radius():
    with pytest.raises(ValueError):
        aperture_coverage_mask((10, 10), 5.0, 5.0, 0.0)


def test_coverage_mask_out_of_bounds_returns_zero():
    mask = aperture_coverage_mask((10, 10), -50.0, -50.0, 3.0)
    assert np.all(mask == 0.0)


def test_estimate_local_sky_recovers_known_background_with_source_excluded():
    shape = (61, 61)
    data = np.full(shape, 100.0)
    yy, xx = np.mgrid[0:61, 0:61]
    star = 5000.0 * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * 2.0**2))
    data = data + star

    sky = estimate_local_sky(data, 30.0, 30.0, r_in=12.0, r_out=18.0)
    assert sky.median == pytest.approx(100.0, abs=1.0)
    assert sky.n_pixels > 0


def test_estimate_local_sky_rejects_invalid_radii():
    with pytest.raises(ValueError):
        estimate_local_sky(np.zeros((10, 10)), 5, 5, r_in=10, r_out=5)


def test_aperture_photometry_recovers_known_flux_for_isolated_gaussian_star():
    background_level = 200.0
    true_flux = 50000.0
    sigma = 2.5
    yy, xx = np.mgrid[0:81, 0:81]
    star = true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - 40) ** 2 + (yy - 40) ** 2)) / (2 * sigma**2))
    data = background_level + star
    uncertainty = np.sqrt(np.clip(data, 0, None))

    measurements = aperture_photometry(
        data, uncertainty, 40.0, 40.0, radii=[3 * sigma, 5 * sigma, 8 * sigma], sky_r_in=20.0, sky_r_out=28.0
    )
    # con 8 sigma de radio, la apertura contiene prácticamente todo el flujo
    wide = measurements[-1]
    assert wide.net_flux == pytest.approx(true_flux, rel=0.02)
    assert wide.snr is not None and wide.snr > 50


def test_aperture_photometry_curve_of_growth_is_monotonically_increasing():
    yy, xx = np.mgrid[0:61, 0:61]
    star = 20000.0 / (2 * math.pi * 3.0**2) * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * 3.0**2))
    data = 150.0 + star
    uncertainty = np.sqrt(np.clip(data, 0, None))

    measurements = aperture_photometry(data, uncertainty, 30.0, 30.0, radii=[2, 4, 6, 10, 14], sky_r_in=18.0, sky_r_out=24.0)
    fluxes = [m.net_flux for m in measurements]
    assert all(later >= earlier - 1e-6 for earlier, later in zip(fluxes, fluxes[1:]))


def test_aperture_photometry_rejects_empty_radii():
    data = np.zeros((10, 10))
    with pytest.raises(ValueError):
        aperture_photometry(data, data, 5, 5, radii=[], sky_r_in=3, sky_r_out=5)


def test_aperture_photometry_magnitude_none_for_nonpositive_flux():
    shape = (21, 21)
    data = np.full(shape, 100.0)  # sin fuente: flujo neto ~ 0 tras restar cielo
    uncertainty = np.sqrt(data)
    measurements = aperture_photometry(data, uncertainty, 10.0, 10.0, radii=[3.0], sky_r_in=6.0, sky_r_out=9.0)
    assert measurements[0].magnitude is None


def _isolated_gaussian_star(shape=(101, 101), center=(50.0, 50.0), true_flux=40000.0, sigma=2.8, background=200.0, seed=3):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    x0, y0 = center
    star = true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data = background + star
    rng = np.random.default_rng(seed)
    data = data + rng.normal(0, math.sqrt(background), shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data, uncertainty


def test_fit_curve_of_growth_recovers_asymptotic_flux_and_monotonic_optimum():
    data, uncertainty = _isolated_gaussian_star()
    radii = [2.0, 4.0, 6.0, 8.0, 11.0, 15.0, 20.0, 26.0]
    measurements = aperture_photometry(data, uncertainty, 50.0, 50.0, radii=radii, sky_r_in=30.0, sky_r_out=40.0)

    fit = fit_curve_of_growth(measurements)

    assert fit.asymptotic_flux == pytest.approx(40000.0, rel=0.1)
    assert fit.optimal_radius_px in radii
    # el radio óptimo debe capturar la mayor parte del flujo, no un recorte extremo
    assert 0.5 < fit.flux_fraction_at_optimal <= 1.05
    assert fit.rms_residual < 0.05 * fit.asymptotic_flux
    assert fit.scale_radius_px > 0


def test_fit_curve_of_growth_optimal_radius_maximizes_measured_snr():
    data, uncertainty = _isolated_gaussian_star()
    radii = [2.0, 4.0, 6.0, 8.0, 11.0, 15.0, 20.0, 26.0]
    measurements = aperture_photometry(data, uncertainty, 50.0, 50.0, radii=radii, sky_r_in=30.0, sky_r_out=40.0)

    fit = fit_curve_of_growth(measurements)

    best_measured = max((m for m in measurements if m.snr is not None), key=lambda m: m.snr)
    assert fit.optimal_radius_px == pytest.approx(best_measured.radius_px)
    assert fit.optimal_snr == pytest.approx(best_measured.snr)


def test_fit_curve_of_growth_rejects_too_few_radii():
    data, uncertainty = _isolated_gaussian_star()
    measurements = aperture_photometry(data, uncertainty, 50.0, 50.0, radii=[4.0, 8.0, 12.0], sky_r_in=30.0, sky_r_out=40.0)
    with pytest.raises(ValueError):
        fit_curve_of_growth(measurements)
