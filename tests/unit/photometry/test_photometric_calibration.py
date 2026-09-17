from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.photometry.calibration import fit_zeropoint


def test_fit_zeropoint_recovers_exact_constant_offset():
    true_zeropoint = 24.7
    instrumental = [-10.0, -9.5, -8.8, -11.2, -9.9]
    catalog = [m + true_zeropoint for m in instrumental]

    fit = fit_zeropoint(instrumental, catalog)

    assert fit.zeropoint_mag == pytest.approx(true_zeropoint, abs=1e-6)
    assert fit.n_stars_used == 5
    assert fit.n_stars_rejected == 0
    assert fit.rms_residual_mag == pytest.approx(0.0, abs=1e-6)


def test_fit_zeropoint_rejects_outlier_star():
    true_zeropoint = 25.0
    instrumental = [-10.0, -9.5, -8.8, -11.2, -9.9, -10.5]
    catalog = [m + true_zeropoint for m in instrumental]
    catalog[3] += 3.0  # una estrella con cruce de catálogo erróneo / variable

    fit = fit_zeropoint(instrumental, catalog, sigma_clip=3.0)

    assert fit.zeropoint_mag == pytest.approx(true_zeropoint, abs=0.05)
    assert fit.n_stars_rejected >= 1
    assert fit.n_stars_used == 6 - fit.n_stars_rejected


def test_fit_zeropoint_used_mask_identifies_the_real_outlier_by_index():
    true_zeropoint = 25.0
    instrumental = [-10.0, -9.5, -8.8, -11.2, -9.9, -10.5]
    catalog = [m + true_zeropoint for m in instrumental]
    catalog[3] += 3.0  # misma estrella deliberadamente inconsistente

    fit = fit_zeropoint(instrumental, catalog, sigma_clip=3.0)

    assert len(fit.used_mask) == len(instrumental)
    assert sum(fit.used_mask) == fit.n_stars_used
    assert fit.used_mask[3] is False
    assert all(fit.used_mask[i] for i in (0, 1, 2, 4, 5))


def test_fit_zeropoint_used_mask_is_all_true_without_outliers():
    true_zeropoint = 24.7
    instrumental = [-10.0, -9.5, -8.8, -11.2, -9.9]
    catalog = [m + true_zeropoint for m in instrumental]

    fit = fit_zeropoint(instrumental, catalog)

    assert fit.used_mask == (True, True, True, True, True)


def test_fit_zeropoint_single_star_has_zero_uncertainty():
    fit = fit_zeropoint([-10.0], [15.0])

    assert fit.zeropoint_mag == pytest.approx(25.0)
    assert fit.zeropoint_uncertainty_mag == pytest.approx(0.0)
    assert fit.n_stars_used == 1


def test_fit_zeropoint_rejects_mismatched_lengths():
    with pytest.raises(ValueError):
        fit_zeropoint([-10.0, -9.0], [15.0])


def test_fit_zeropoint_rejects_empty_input():
    with pytest.raises(ValueError):
        fit_zeropoint([], [])


def test_fit_zeropoint_uncertainty_shrinks_with_more_stars():
    rng = np.random.default_rng(0)
    true_zeropoint = 24.0
    n_small, n_large = 4, 40
    instrumental_small = list(rng.uniform(-12, -8, n_small))
    catalog_small = [m + true_zeropoint + rng.normal(0, 0.05) for m in instrumental_small]
    instrumental_large = list(rng.uniform(-12, -8, n_large))
    catalog_large = [m + true_zeropoint + rng.normal(0, 0.05) for m in instrumental_large]

    fit_small = fit_zeropoint(instrumental_small, catalog_small)
    fit_large = fit_zeropoint(instrumental_large, catalog_large)

    assert fit_large.zeropoint_uncertainty_mag < fit_small.zeropoint_uncertainty_mag
