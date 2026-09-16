"""El caso de uso central de `daophot`: separar el flujo de dos fuentes
que se solapan tanto que una apertura razonable no podría distinguirlas
-- el ajuste simultáneo de PSF sí debe poder, con error pequeño frente
al flujo verdadero conocido de la simulación."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.detection.point_sources import PSFCandidate
from astrophysics_suite.photometry.psf import (
    EmpiricalPSF,
    GaussianPSF,
    MoffatPSF,
    build_empirical_psf,
    compute_psf_fit_diagnostics,
    fit_group_psf_photometry,
    fit_group_psf_photometry_with_position_refinement,
    select_psf_reference_stars,
)


def test_gaussian_psf_integrates_to_approximately_unit_flux():
    psf = GaussianPSF(sigma_x=2.0)
    yy, xx = np.mgrid[-20:21, -20:21]
    total = np.sum(psf.evaluate(xx.astype(float), yy.astype(float)))
    assert total == pytest.approx(1.0, rel=1e-3)


def test_gaussian_psf_fwhm_matches_formula():
    psf = GaussianPSF(sigma_x=3.0)
    assert psf.fwhm_px == pytest.approx(2.0 * math.sqrt(2.0 * math.log(2.0)) * 3.0)


def test_gaussian_psf_rejects_non_positive_sigma():
    with pytest.raises(ValueError):
        GaussianPSF(sigma_x=0.0)


def test_moffat_psf_integrates_to_approximately_unit_flux():
    psf = MoffatPSF(alpha=3.0, beta=2.5)
    yy, xx = np.mgrid[-60:61, -60:61]
    total = np.sum(psf.evaluate(xx.astype(float), yy.astype(float)))
    assert total == pytest.approx(1.0, rel=1e-2)


def test_moffat_psf_rejects_invalid_beta():
    with pytest.raises(ValueError):
        MoffatPSF(alpha=3.0, beta=1.0)


def test_moffat_psf_half_max_at_fwhm_radius():
    psf = MoffatPSF(alpha=4.0, beta=3.0)
    peak = psf.evaluate(np.array([0.0]), np.array([0.0]))[0]
    half_radius = psf.fwhm_px / 2.0
    value_at_half = psf.evaluate(np.array([half_radius]), np.array([0.0]))[0]
    assert value_at_half == pytest.approx(peak / 2.0, rel=1e-6)


def _inject_gaussian_star(data, x0, y0, flux, sigma):
    yy, xx = np.mgrid[0 : data.shape[0], 0 : data.shape[1]]
    data += flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))


def test_fit_group_psf_photometry_recovers_flux_for_isolated_star():
    shape = (61, 61)
    sigma = 2.0
    true_flux = 30000.0
    data = np.full(shape, 100.0)
    _inject_gaussian_star(data, 30.0, 30.0, true_flux, sigma)
    uncertainty = np.sqrt(np.clip(data, 0, None))

    result = fit_group_psf_photometry(data, uncertainty, GaussianPSF(sigma_x=sigma), [(30.0, 30.0)])
    assert len(result) == 1
    assert result[0].flux == pytest.approx(true_flux, rel=0.03)


def test_fit_group_psf_photometry_deblends_two_overlapping_stars():
    shape = (61, 61)
    sigma = 2.2
    flux_a, flux_b = 40000.0, 15000.0
    pos_a, pos_b = (26.0, 30.0), (34.0, 30.0)  # separación de 8px con sigma=2.2 -> perfiles muy solapados

    data = np.full(shape, 150.0)
    _inject_gaussian_star(data, pos_a[0], pos_a[1], flux_a, sigma)
    _inject_gaussian_star(data, pos_b[0], pos_b[1], flux_b, sigma)
    uncertainty = np.sqrt(np.clip(data, 0, None))

    results = fit_group_psf_photometry(data, uncertainty, GaussianPSF(sigma_x=sigma), [pos_a, pos_b])

    assert results[0].flux == pytest.approx(flux_a, rel=0.05)
    assert results[1].flux == pytest.approx(flux_b, rel=0.05)


def test_fit_group_psf_photometry_beats_naive_shared_aperture_for_blended_pair():
    """Demuestra el valor real del ajuste simultáneo: una apertura ingenua
    centrada en cada estrella, sin deconvolucionar, sobreestima
    sistemáticamente el flujo débil por la cola de la estrella brillante
    vecina -- el ajuste de PSF no."""
    shape = (61, 61)
    sigma = 2.2
    flux_a, flux_b = 60000.0, 8000.0
    pos_a, pos_b = (26.0, 30.0), (33.0, 30.0)

    data = np.full(shape, 150.0)
    _inject_gaussian_star(data, pos_a[0], pos_a[1], flux_a, sigma)
    _inject_gaussian_star(data, pos_b[0], pos_b[1], flux_b, sigma)
    uncertainty = np.sqrt(np.clip(data, 0, None))

    results = fit_group_psf_photometry(data, uncertainty, GaussianPSF(sigma_x=sigma), [pos_a, pos_b])
    psf_flux_b = results[1].flux

    from astrophysics_suite.photometry.aperture import aperture_photometry

    naive = aperture_photometry(data, uncertainty, pos_b[0], pos_b[1], radii=[3 * sigma], sky_r_in=15.0, sky_r_out=20.0)
    naive_flux_b = naive[0].net_flux

    assert abs(psf_flux_b - flux_b) < abs(naive_flux_b - flux_b)


def test_fit_group_psf_photometry_rejects_empty_positions():
    with pytest.raises(ValueError):
        fit_group_psf_photometry(np.zeros((10, 10)), np.ones((10, 10)), GaussianPSF(sigma_x=2.0), [])


def test_fit_group_psf_photometry_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        fit_group_psf_photometry(np.zeros((10, 10)), np.ones((5, 5)), GaussianPSF(sigma_x=2.0), [(5.0, 5.0)])


def test_build_empirical_psf_from_single_star_is_peaked_and_normalized():
    shape = (41, 41)
    sigma = 2.0
    data = np.full(shape, 50.0)
    _inject_gaussian_star(data, 20.3, 19.7, 20000.0, sigma)

    psf = build_empirical_psf(data - 50.0, [(20.3, 19.7)], half_size=9, oversample=4)
    assert isinstance(psf, EmpiricalPSF)
    assert psf.template.sum() == pytest.approx(1.0, rel=1e-6)

    peak_index = np.unravel_index(np.argmax(psf.template), psf.template.shape)
    center_index = psf.template.shape[0] // 2
    assert abs(peak_index[0] - center_index) <= psf.oversample
    assert abs(peak_index[1] - center_index) <= psf.oversample


def test_build_empirical_psf_rejects_empty_positions():
    with pytest.raises(ValueError):
        build_empirical_psf(np.zeros((20, 20)), [])


def test_build_empirical_psf_skips_positions_too_close_to_edge():
    data = np.full((20, 20), 10.0)
    with pytest.raises(ValueError):
        build_empirical_psf(data, [(1.0, 1.0)], half_size=9)


def test_position_refinement_recovers_true_position_from_offset_guess():
    shape = (61, 61)
    sigma = 2.0
    true_flux = 30000.0
    true_x, true_y = 30.4, 29.7  # posición subpíxel real, no entera
    data = np.full(shape, 100.0)
    _inject_gaussian_star(data, true_x, true_y, true_flux, sigma)
    uncertainty = np.sqrt(np.clip(data, 0, None))

    initial_guess = (true_x + 1.3, true_y - 1.1)  # adivinanza inicial deliberadamente descentrada
    results = fit_group_psf_photometry_with_position_refinement(
        data, uncertainty, GaussianPSF(sigma_x=sigma), [initial_guess], max_position_shift_px=3.0
    )

    assert len(results) == 1
    assert results[0].x == pytest.approx(true_x, abs=0.15)
    assert results[0].y == pytest.approx(true_y, abs=0.15)
    assert results[0].flux == pytest.approx(true_flux, rel=0.05)


def test_position_refinement_improves_on_fixed_position_flux_when_initial_guess_is_off():
    shape = (61, 61)
    sigma = 2.0
    true_flux = 30000.0
    true_x, true_y = 30.0, 30.0
    data = np.full(shape, 100.0)
    _inject_gaussian_star(data, true_x, true_y, true_flux, sigma)
    uncertainty = np.sqrt(np.clip(data, 0, None))

    offset_guess = (true_x + 1.5, true_y - 1.2)
    fixed_result = fit_group_psf_photometry(data, uncertainty, GaussianPSF(sigma_x=sigma), [offset_guess])[0]
    refined_result = fit_group_psf_photometry_with_position_refinement(
        data, uncertainty, GaussianPSF(sigma_x=sigma), [offset_guess], max_position_shift_px=3.0
    )[0]

    assert abs(refined_result.flux - true_flux) < abs(fixed_result.flux - true_flux)


def test_position_refinement_rejects_empty_positions():
    with pytest.raises(ValueError):
        fit_group_psf_photometry_with_position_refinement(np.zeros((10, 10)), np.ones((10, 10)), GaussianPSF(sigma_x=2.0), [])


def test_compute_psf_fit_diagnostics_reduced_chi2_near_one_for_correct_model():
    shape = (61, 61)
    sigma = 2.2
    true_flux = 40000.0
    rng = np.random.default_rng(11)
    data = np.full(shape, 200.0) + rng.normal(0, 5.0, shape)
    _inject_gaussian_star(data, 30.0, 30.0, true_flux, sigma)
    uncertainty = np.full(shape, 5.0)

    psf_model = GaussianPSF(sigma_x=sigma)
    results = fit_group_psf_photometry(data, uncertainty, psf_model, [(30.0, 30.0)])
    diagnostics = compute_psf_fit_diagnostics(data, uncertainty, psf_model, results, fit_half_size=10)

    assert 0.5 < diagnostics.reduced_chi2 < 2.0
    assert diagnostics.n_pixels_used > 0
    y_min, y_max, x_min, x_max = diagnostics.bbox
    assert diagnostics.residual_image.shape == (y_max - y_min, x_max - x_min)
    assert diagnostics.sky_level == pytest.approx(200.0, abs=3.0)


def test_compute_psf_fit_diagnostics_flags_wrong_psf_model_with_higher_chi2():
    shape = (61, 61)
    true_sigma = 2.2
    true_flux = 40000.0
    rng = np.random.default_rng(12)
    data = np.full(shape, 200.0) + rng.normal(0, 5.0, shape)
    _inject_gaussian_star(data, 30.0, 30.0, true_flux, true_sigma)
    uncertainty = np.full(shape, 5.0)

    correct_model = GaussianPSF(sigma_x=true_sigma)
    wrong_model = GaussianPSF(sigma_x=true_sigma * 2.5)  # modelo deliberadamente mal ajustado

    correct_results = fit_group_psf_photometry(data, uncertainty, correct_model, [(30.0, 30.0)])
    wrong_results = fit_group_psf_photometry(data, uncertainty, wrong_model, [(30.0, 30.0)])

    correct_diag = compute_psf_fit_diagnostics(data, uncertainty, correct_model, correct_results, fit_half_size=10)
    wrong_diag = compute_psf_fit_diagnostics(data, uncertainty, wrong_model, wrong_results, fit_half_size=10)

    assert wrong_diag.reduced_chi2 > correct_diag.reduced_chi2 * 3


def test_compute_psf_fit_diagnostics_rejects_empty_results():
    with pytest.raises(ValueError):
        compute_psf_fit_diagnostics(np.zeros((10, 10)), np.ones((10, 10)), GaussianPSF(sigma_x=2.0), [])


def _candidate(x, y, flux, ellipticity=0.05, snr=50.0):
    return PSFCandidate(x=x, y=y, flux=flux, fwhm_px=3.0, ellipticity=ellipticity, sharpness=1.0, snr=snr)


def test_select_psf_reference_stars_rejects_close_neighbors():
    candidates = [_candidate(30.0, 30.0, 20000.0), _candidate(35.0, 30.0, 15000.0)]  # separados 5px
    selected = select_psf_reference_stars(candidates, min_separation_px=15.0)
    assert selected == []  # ambas se rechazan mutuamente por falta de aislamiento


def test_select_psf_reference_stars_rejects_elongated_and_low_snr():
    candidates = [
        _candidate(10.0, 10.0, 20000.0, ellipticity=0.05, snr=50.0),  # buena
        _candidate(60.0, 60.0, 25000.0, ellipticity=0.6, snr=50.0),  # demasiado alargada
        _candidate(90.0, 90.0, 18000.0, ellipticity=0.05, snr=3.0),  # S/N insuficiente
    ]
    selected = select_psf_reference_stars(candidates, min_separation_px=15.0, max_ellipticity=0.3, min_snr=10.0)
    assert len(selected) == 1
    assert selected[0].x == 10.0 and selected[0].y == 10.0


def test_select_psf_reference_stars_sorts_by_brightness_and_caps_max_stars():
    candidates = [_candidate(x, 10.0, flux) for x, flux in [(10.0, 5000.0), (200.0, 30000.0), (400.0, 15000.0)]]
    selected = select_psf_reference_stars(candidates, min_separation_px=15.0, max_stars=2)
    assert len(selected) == 2
    assert [c.flux for c in selected] == [30000.0, 15000.0]


def test_select_psf_reference_stars_returns_empty_when_none_qualify():
    candidates = [_candidate(10.0, 10.0, 5000.0, ellipticity=0.9)]
    selected = select_psf_reference_stars(candidates, max_ellipticity=0.3)
    assert selected == []
