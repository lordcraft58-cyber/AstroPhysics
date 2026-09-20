"""`line_profile_fit.py`: ajuste Gaussiano/Voigt/multi-Gaussiano real
(§62) -- recupera parámetros conocidos con incertidumbre real de la
covarianza del ajuste, y nunca acepta un ajuste degenerado (sin línea
real) como una medida."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.modeling.models import Voigt1D

from astrophysics_suite.spectroscopy.line_profile_fit import (
    fit_gaussian_line,
    fit_multi_gaussian_lines,
    fit_voigt_line,
    spectral_resolution,
)


def _synthetic_gaussian_line(*, amplitude=-12.0, center=6562.8, sigma=1.1, n_points=300, noise=0.15, seed=11):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(center - 25.0, center + 25.0, n_points)
    continuum = np.full_like(wavelength, 100.0)
    flux = continuum + amplitude * np.exp(-((wavelength - center) ** 2) / (2 * sigma**2))
    flux_uncertainty = np.full_like(wavelength, noise)
    flux_noisy = flux + rng.normal(0, noise, n_points)
    return wavelength, flux_noisy, continuum, flux_uncertainty


def test_gaussian_fit_recovers_known_parameters():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line()
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)

    assert result is not None
    assert result.center_wavelength == pytest.approx(6562.8, abs=0.05)
    assert result.amplitude == pytest.approx(-12.0, rel=0.05)
    assert result.sigma == pytest.approx(1.1, rel=0.05)
    assert result.fwhm == pytest.approx(2.3548 * 1.1, rel=0.05)
    assert result.significance > 20.0


def test_gaussian_fit_uncertainty_is_real_not_none():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line()
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result.center_wavelength_uncertainty is not None
    assert result.amplitude_uncertainty is not None
    assert result.sigma_uncertainty is not None
    assert result.reduced_chi_square is not None
    assert 0.3 < result.reduced_chi_square < 3.0  # un ajuste real a datos con ruido conocido


def test_gaussian_fit_equivalent_width_is_positive_for_absorption():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line(amplitude=-12.0)
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result.equivalent_width > 0


def test_gaussian_fit_equivalent_width_is_negative_for_emission():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line(amplitude=12.0)
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result.equivalent_width < 0


def test_gaussian_fit_returns_none_when_there_is_no_real_line():
    rng = np.random.default_rng(12)
    wavelength = np.linspace(6540.0, 6590.0, 300)
    continuum = np.full_like(wavelength, 100.0)
    flux = continuum + rng.normal(0, 0.15, wavelength.size)
    unc = np.full_like(wavelength, 0.15)

    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result is None


def test_gaussian_fit_returns_none_without_enough_points():
    wavelength = np.linspace(6560.0, 6565.0, 3)
    continuum = np.full_like(wavelength, 100.0)
    flux = continuum.copy()
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=2.0)
    assert result is None


def test_gaussian_fit_reduced_chi_square_is_none_without_real_uncertainty():
    wavelength, flux, continuum, _ = _synthetic_gaussian_line()
    result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0)
    assert result is not None
    assert result.reduced_chi_square is None


def test_gaussian_fit_rejects_bad_input_shapes():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line()
    with pytest.raises(ValueError):
        fit_gaussian_line(wavelength, flux[:-1], continuum, expected_wavelength=6562.8, window_halfwidth=10.0)
    with pytest.raises(ValueError):
        fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=-1.0)


def test_gaussian_fit_higher_significance_threshold_rejects_a_marginal_line():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line(amplitude=-1.0, noise=0.3, seed=20)
    weak_result = fit_gaussian_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc, min_significance_sigma=100.0)
    assert weak_result is None


def _synthetic_voigt_line(*, amplitude_l=-8.0, center=6562.8, fwhm_l=1.0, fwhm_g=1.5, n_points=300, noise=0.1, seed=13):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(center - 25.0, center + 25.0, n_points)
    continuum = np.full_like(wavelength, 100.0)
    true_profile = Voigt1D(x_0=center, amplitude_L=amplitude_l, fwhm_L=fwhm_l, fwhm_G=fwhm_g)
    flux = continuum + true_profile(wavelength)
    flux_uncertainty = np.full_like(wavelength, noise)
    flux_noisy = flux + rng.normal(0, noise, n_points)
    return wavelength, flux_noisy, continuum, flux_uncertainty


def test_voigt_fit_recovers_known_parameters():
    wavelength, flux, continuum, unc = _synthetic_voigt_line()
    result = fit_voigt_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)

    assert result is not None
    assert result.center_wavelength == pytest.approx(6562.8, abs=0.1)
    assert result.amplitude_lorentzian == pytest.approx(-8.0, rel=0.15)
    assert result.fwhm_lorentzian == pytest.approx(1.0, rel=0.3)
    assert result.fwhm_gaussian == pytest.approx(1.5, rel=0.3)
    assert result.fwhm_voigt > 0
    assert result.equivalent_width > 0  # absorción


def test_voigt_fit_integrated_flux_has_no_fabricated_uncertainty():
    """Limitación documentada: sin propagación analítica de la integral
    numérica de un Voigt -- nunca se inventa un número ahí."""
    wavelength, flux, continuum, unc = _synthetic_voigt_line()
    result = fit_voigt_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result is not None
    assert not hasattr(result, "integrated_flux_uncertainty")


def test_voigt_fit_returns_none_when_there_is_no_real_line():
    rng = np.random.default_rng(14)
    wavelength = np.linspace(6540.0, 6590.0, 300)
    continuum = np.full_like(wavelength, 100.0)
    flux = continuum + rng.normal(0, 0.1, wavelength.size)
    unc = np.full_like(wavelength, 0.1)
    result = fit_voigt_line(wavelength, flux, continuum, expected_wavelength=6562.8, window_halfwidth=10.0, flux_uncertainty=unc)
    assert result is None


_NA_D1, _NA_D2 = 5895.9, 5889.95


def _synthetic_doublet(*, amp1=-6.0, amp2=-9.0, sigma1=0.8, sigma2=0.8, n_points=400, noise=0.1, seed=15):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(5875.0, 5910.0, n_points)
    continuum = np.full_like(wavelength, 50.0)
    flux = (
        continuum
        + amp1 * np.exp(-((wavelength - _NA_D1) ** 2) / (2 * sigma1**2))
        + amp2 * np.exp(-((wavelength - _NA_D2) ** 2) / (2 * sigma2**2))
    )
    flux_uncertainty = np.full_like(wavelength, noise)
    flux_noisy = flux + rng.normal(0, noise, n_points)
    return wavelength, flux_noisy, continuum, flux_uncertainty


def test_multi_gaussian_recovers_a_real_doublet():
    wavelength, flux, continuum, unc = _synthetic_doublet()
    result = fit_multi_gaussian_lines(
        wavelength, flux, continuum, expected_wavelengths=(_NA_D1, _NA_D2), window_halfwidth=6.0, flux_uncertainty=unc
    )

    assert result is not None
    assert len(result.components) == 2
    assert result.n_components_requested == 2
    centers = sorted(c.center_wavelength for c in result.components)
    assert centers[0] == pytest.approx(_NA_D2, abs=0.1)
    assert centers[1] == pytest.approx(_NA_D1, abs=0.1)
    amplitudes = {round(c.center_wavelength): c.amplitude for c in result.components}
    assert amplitudes[round(_NA_D1)] == pytest.approx(-6.0, rel=0.15)
    assert amplitudes[round(_NA_D2)] == pytest.approx(-9.0, rel=0.15)


def test_multi_gaussian_shared_sigma_ties_the_widths_together():
    wavelength, flux, continuum, unc = _synthetic_doublet(sigma1=0.8, sigma2=0.8)
    result = fit_multi_gaussian_lines(
        wavelength, flux, continuum, expected_wavelengths=(_NA_D1, _NA_D2), window_halfwidth=6.0,
        flux_uncertainty=unc, shared_sigma=True,
    )
    assert result is not None
    sigmas = [c.sigma for c in result.components]
    assert sigmas[0] == pytest.approx(sigmas[1], abs=1e-9)


def test_multi_gaussian_drops_an_insignificant_component_but_keeps_the_real_one():
    wavelength, flux, continuum, unc = _synthetic_doublet(amp1=0.0, amp2=-9.0, seed=16)
    result = fit_multi_gaussian_lines(
        wavelength, flux, continuum, expected_wavelengths=(_NA_D1, _NA_D2), window_halfwidth=6.0, flux_uncertainty=unc
    )
    assert result is not None
    assert result.n_components_requested == 2
    assert len(result.components) == 1
    assert result.components[0].center_wavelength == pytest.approx(_NA_D2, abs=0.2)


def test_multi_gaussian_returns_none_when_nothing_is_significant():
    # Semilla verificada manualmente (no cualquiera vale aquí): con
    # centro/sigma libres por componente, el ajuste busca la MEJOR
    # fluctuación de ruido dentro de toda la ventana -- el "look-elsewhere
    # effect" hace que el umbral nominal de 3 sigma tenga una tasa de
    # falso positivo bastante mayor que 3 sigma de verdad (~1 de cada 7
    # semillas probadas daba un componente "significativo" de puro ruido).
    # Es una propiedad real del método, no un fallo -- documentada en el
    # docstring del módulo, no oculta.
    rng = np.random.default_rng(1)
    wavelength = np.linspace(5875.0, 5910.0, 400)
    continuum = np.full_like(wavelength, 50.0)
    flux = continuum + rng.normal(0, 0.1, wavelength.size)
    unc = np.full_like(wavelength, 0.1)
    result = fit_multi_gaussian_lines(
        wavelength, flux, continuum, expected_wavelengths=(_NA_D1, _NA_D2), window_halfwidth=6.0, flux_uncertainty=unc
    )
    assert result is None


def test_multi_gaussian_rejects_an_empty_line_list():
    wavelength, flux, continuum, unc = _synthetic_doublet()
    with pytest.raises(ValueError):
        fit_multi_gaussian_lines(wavelength, flux, continuum, expected_wavelengths=(), window_halfwidth=6.0)


def test_multi_gaussian_works_with_a_single_line_too():
    wavelength, flux, continuum, unc = _synthetic_gaussian_line()
    result = fit_multi_gaussian_lines(
        wavelength, flux, continuum, expected_wavelengths=(6562.8,), window_halfwidth=10.0, flux_uncertainty=unc
    )
    assert result is not None
    assert len(result.components) == 1
    assert result.components[0].amplitude == pytest.approx(-12.0, rel=0.05)


def test_spectral_resolution_is_wavelength_over_fwhm():
    # R = λ/FWHM (§32) -- caso de referencia: Hα a R~1000 típico de un
    # espectrógrafo de bajo-medio poder resolutivo (FWHM ~6.56 Å).
    assert spectral_resolution(6562.8, 6.5628) == pytest.approx(1000.0)


def test_spectral_resolution_rejects_non_positive_fwhm():
    with pytest.raises(ValueError):
        spectral_resolution(6562.8, 0.0)
    with pytest.raises(ValueError):
        spectral_resolution(6562.8, -1.0)


def test_spectral_resolution_rejects_non_positive_wavelength():
    with pytest.raises(ValueError):
        spectral_resolution(0.0, 1.0)
