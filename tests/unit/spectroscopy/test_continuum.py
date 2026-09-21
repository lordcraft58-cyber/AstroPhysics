from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.continuum import fit_continuum, normalize_by_continuum


def _spectrum_with_lines(seed=0):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(4000.0, 7000.0, 400)
    true_continuum = 100.0 + 0.01 * (wavelength - 5000.0)
    flux = true_continuum.copy()
    flux[150:155] += 400.0  # línea de emisión fuerte
    flux[300:305] -= 60.0  # línea de absorción
    flux += rng.normal(0, 1.5, wavelength.size)
    return wavelength, flux, true_continuum


def test_fit_continuum_recovers_true_continuum_despite_lines():
    wavelength, flux, true_continuum = _spectrum_with_lines()
    result = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0)
    np.testing.assert_allclose(result.continuum, true_continuum, atol=2.0)
    assert result.n_rejected >= 8  # las 2 líneas inyectadas (5 px cada una) deben quedar fuera del ajuste


def test_fit_continuum_emission_only_keeps_absorption_line_in_fit():
    wavelength, flux, _ = _spectrum_with_lines()
    # la línea de absorción inyectada vive en los índices 300:305
    result_both = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, reject="both")
    result_emission = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, reject="emission")

    assert not result_both.used_mask[302]  # "both" rechaza la absorción
    assert result_emission.used_mask[302]  # "emission" la conserva en el ajuste


def test_fit_continuum_absorption_only_keeps_emission_line_in_fit():
    wavelength, flux, _ = _spectrum_with_lines()
    # la línea de emisión inyectada vive en los índices 150:155
    result_both = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, reject="both")
    result_absorption = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, reject="absorption")

    assert not result_both.used_mask[152]  # "both" rechaza la emisión
    assert result_absorption.used_mask[152]  # "absorption" la conserva en el ajuste


def test_fit_continuum_rejects_invalid_reject_mode():
    wavelength = np.linspace(0, 1, 20)
    with pytest.raises(ValueError):
        fit_continuum(wavelength, wavelength, degree=1, reject="invalid")


def test_fit_continuum_rejects_shape_mismatch():
    with pytest.raises(ValueError):
        fit_continuum(np.zeros(10), np.zeros(9), degree=1)


def test_fit_continuum_requires_enough_points():
    with pytest.raises(ValueError):
        fit_continuum(np.array([1.0, 2.0]), np.array([1.0, 2.0]), degree=3)


def test_normalize_by_continuum_gives_unit_level_away_from_lines():
    wavelength, flux, _ = _spectrum_with_lines()
    result = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0)
    normalized = normalize_by_continuum(flux, result)
    quiet_region = normalized[50:100]
    assert np.median(quiet_region) == pytest.approx(1.0, abs=0.05)


def test_fit_continuum_spline_recovers_true_continuum_despite_lines():
    """§19: el spline es una alternativa real al polinomio para el
    continuo -- sigue recuperando el continuo verdadero rechazando las
    mismas líneas inyectadas."""
    wavelength, flux, true_continuum = _spectrum_with_lines()
    result = fit_continuum(wavelength, flux, degree=3, sigma_clip=3.0, method="spline")
    assert result.method == "spline"
    assert result.coefficients.size == 0  # un spline no tiene coeficientes polinómicos que reportar
    np.testing.assert_allclose(result.continuum, true_continuum, atol=3.0)
    assert result.n_rejected >= 8


def test_fit_continuum_rejects_unknown_method():
    wavelength = np.linspace(4000.0, 5000.0, 50)
    with pytest.raises(ValueError):
        fit_continuum(wavelength, wavelength, degree=1, method="lagrange")


def test_fit_continuum_regions_restricts_the_fit_to_manually_chosen_continuum_windows():
    """§19: selección manual de regiones de continuo -- un grado alto
    que normalmente seguiría de cerca hasta el ruido de las líneas debe
    quedarse cerca del continuo real cuando el ajuste solo ve las
    regiones reales indicadas a mano, lejos de ambas líneas inyectadas
    (líneas en índices 150:155 y 300:305 de 400 puntos entre 4000-7000 Å,
    es decir alrededor de 5127 Å y 5771 Å)."""
    wavelength, flux, true_continuum = _spectrum_with_lines()
    quiet_regions = ((4000.0, 5000.0), (6200.0, 7000.0))

    result = fit_continuum(wavelength, flux, degree=1, sigma_clip=3.0, regions=quiet_regions)

    np.testing.assert_allclose(result.continuum, true_continuum, atol=2.0)
    # ningún punto fuera de las regiones manuales participó nunca en el ajuste final
    outside = ~((wavelength >= 4000.0) & (wavelength <= 5000.0)) & ~((wavelength >= 6200.0) & (wavelength <= 7000.0))
    assert not np.any(result.used_mask & outside)


def test_fit_continuum_regions_rejects_honestly_when_nothing_real_falls_inside():
    wavelength = np.linspace(4000.0, 5000.0, 50)
    flux = np.full(50, 100.0)
    with pytest.raises(ValueError):
        fit_continuum(wavelength, flux, degree=1, regions=((9000.0, 9100.0),))
