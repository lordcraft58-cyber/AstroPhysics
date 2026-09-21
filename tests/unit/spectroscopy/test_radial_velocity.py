"""`radial_velocity.py`: Doppler de una línea, combinación multi-línea
con dispersión explícita (§59), y correlación cruzada (§58) -- nunca
inventa una velocidad cuando no hay evidencia real que medir."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.line_catalog import LineType, SpectralLine
from astrophysics_suite.spectroscopy.radial_velocity import (
    C_KM_S,
    cross_correlate_radial_velocity,
    measure_multi_line_radial_velocity,
    velocity_from_wavelength_shift,
)


def test_classical_velocity_recovers_a_known_redshift():
    rest = 6562.8
    true_velocity = 150.0
    observed = rest * (1.0 + true_velocity / C_KM_S)
    velocity = velocity_from_wavelength_shift(observed, rest)
    assert velocity == pytest.approx(true_velocity, abs=1e-6)


def test_blueshift_is_negative():
    rest = 5000.0
    observed = rest * (1.0 - 200.0 / C_KM_S)
    assert velocity_from_wavelength_shift(observed, rest) < 0


def test_relativistic_and_classical_agree_at_low_velocity():
    rest = 5000.0
    observed = rest * (1.0 + 50.0 / C_KM_S)
    classical = velocity_from_wavelength_shift(observed, rest, relativistic=False)
    relativistic = velocity_from_wavelength_shift(observed, rest, relativistic=True)
    assert classical == pytest.approx(relativistic, rel=1e-4)


def test_relativistic_and_classical_diverge_at_high_fraction_of_c():
    rest = 5000.0
    observed = rest * 1.5  # z=0.5, una fracción no despreciable de c
    classical = velocity_from_wavelength_shift(observed, rest, relativistic=False)
    relativistic = velocity_from_wavelength_shift(observed, rest, relativistic=True)
    assert abs(classical - relativistic) > 1000.0  # difieren de verdad, no solo por redondeo
    assert relativistic < C_KM_S  # la fórmula relativista nunca supera c


def test_works_elementwise_on_an_array_for_a_velocity_axis():
    rest = 5000.0
    wavelength = np.array([4995.0, 5000.0, 5005.0])
    velocities = velocity_from_wavelength_shift(wavelength, rest)
    assert velocities.shape == wavelength.shape
    assert velocities[1] == pytest.approx(0.0, abs=1e-6)
    assert velocities[0] < 0 < velocities[2]


def test_rejects_nonpositive_rest_wavelength():
    with pytest.raises(ValueError):
        velocity_from_wavelength_shift(5000.0, 0.0)


def _synthetic_absorption_spectrum(lines_rest, *, velocity_km_s, n_points=3000, seed=4, noise=0.15):
    # Muestreo más fino que la fila de arco sintética de otros tests
    # (3000 puntos en 3400 A ~= 1.1 A/px) -- necesario para que un
    # centroide de momento simple (measure_line, sin ajuste Gaussiano)
    # resuelva de verdad el perfil de linea de sigma=1.2 A en vez de
    # arrastrarse hacia el centro simetrico de la ventana por puro ruido
    # de muestras infrarresueltas -- ver docs/audit/58-... para la
    # investigacion completa de este sesgo.
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(3800.0, 7200.0, n_points)
    continuum_true = 100.0 + 0.001 * (wavelength - 5500.0)
    flux = continuum_true.copy()
    for rest in lines_rest:
        observed = rest * (1.0 + velocity_km_s / C_KM_S)
        flux -= 15.0 * np.exp(-((wavelength - observed) ** 2) / (2 * 1.2**2))
    flux += rng.normal(0, noise, n_points)
    return wavelength, flux, continuum_true


_BALMER_REST = (6562.8, 4861.3, 4340.5, 4101.7)


def test_multi_line_rv_recovers_a_known_velocity_from_several_real_lines():
    true_velocity = 85.0
    lines = tuple(SpectralLine(w, f"H {w}", "H", line_type=LineType.ABSORPTION) for w in _BALMER_REST)
    wavelength, flux, continuum_true = _synthetic_absorption_spectrum(_BALMER_REST, velocity_km_s=true_velocity)
    continuum_fit = fit_continuum(wavelength, flux, degree=1, reject="absorption")

    result = measure_multi_line_radial_velocity(wavelength, flux, continuum_fit.continuum, lines, window_halfwidth=6.0)

    assert result.n_lines_used == len(lines)
    assert result.combined_velocity_km_s == pytest.approx(true_velocity, abs=6.0)
    assert result.velocity_dispersion_km_s is not None
    assert result.combined_velocity_uncertainty_km_s is not None
    assert result.all_lines_measured


def test_multi_line_rv_skips_lines_outside_range_instead_of_inventing_them():
    lines = (
        SpectralLine(6562.8, "H-alpha", "H"),
        SpectralLine(99999.0, "fuera de rango", "X"),  # nunca puede caer en el espectro sintético
    )
    wavelength, flux, continuum_true = _synthetic_absorption_spectrum((6562.8,), velocity_km_s=0.0)
    continuum_fit = fit_continuum(wavelength, flux, degree=1, reject="absorption")

    result = measure_multi_line_radial_velocity(wavelength, flux, continuum_fit.continuum, lines, window_halfwidth=10.0)

    assert result.n_lines_used == 1
    assert result.n_lines_requested == 2
    assert not result.all_lines_measured
    assert result.velocity_dispersion_km_s is None  # una sola línea: no hay dispersión que estimar


def test_multi_line_rv_with_zero_measurable_lines_returns_none_not_zero():
    lines = (SpectralLine(99999.0, "fuera de rango", "X"),)
    wavelength, flux, continuum_true = _synthetic_absorption_spectrum((), velocity_km_s=0.0)
    continuum_fit = fit_continuum(wavelength, flux, degree=1, reject="both")

    result = measure_multi_line_radial_velocity(wavelength, flux, continuum_fit.continuum, lines, window_halfwidth=10.0)

    assert result.n_lines_used == 0
    assert result.combined_velocity_km_s is None
    assert result.combined_velocity_uncertainty_km_s is None


def test_velocity_uncertainty_per_line_is_honestly_none():
    lines = (SpectralLine(6562.8, "H-alpha", "H"),)
    wavelength, flux, continuum_true = _synthetic_absorption_spectrum((6562.8,), velocity_km_s=0.0)
    continuum_fit = fit_continuum(wavelength, flux, degree=1, reject="absorption")

    result = measure_multi_line_radial_velocity(wavelength, flux, continuum_fit.continuum, lines, window_halfwidth=10.0)

    assert result.measurements[0].velocity_uncertainty_km_s is None


def _synthetic_normalized_template(n_points=2000, seed=5):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(4000.0, 7000.0, n_points)
    flux = np.ones(n_points)
    for rest in _BALMER_REST:
        flux -= 0.3 * np.exp(-((wavelength - rest) ** 2) / (2 * 1.5**2))
    flux += rng.normal(0, 0.01, n_points)
    return wavelength, flux


def test_cross_correlation_recovers_a_known_shift():
    template_wavelength, template_flux = _synthetic_normalized_template()
    true_velocity = 120.0
    observed_wavelength = template_wavelength * (1.0 + true_velocity / C_KM_S)
    observed_flux = template_flux.copy()

    result = cross_correlate_radial_velocity(
        observed_wavelength, observed_flux, template_wavelength, template_flux,
        velocity_min_km_s=-400.0, velocity_max_km_s=400.0, velocity_step_km_s=2.0,
    )

    assert result.best_velocity_km_s == pytest.approx(true_velocity, abs=5.0)
    assert result.peak_correlation > 0.9
    assert result.n_overlap_points > 100


def test_cross_correlation_reports_nan_correlation_where_there_is_no_overlap():
    # Ventana ESTRECHA a propósito (a diferencia de la plantilla amplia
    # de otros tests): con un rango de solo 50 A, un corrimiento de
    # +-50000 km/s (~17% de c, cientos de A de desplazamiento absoluto)
    # saca la plantilla completamente fuera del rango observado -- con
    # una plantilla ancha (miles de A) ese mismo corrimiento relativo
    # seguiría solapando, por eso hace falta esta ventana dedicada.
    rng = np.random.default_rng(6)
    narrow_wavelength = np.linspace(6540.0, 6590.0, 200)
    narrow_flux = 1.0 - 0.3 * np.exp(-((narrow_wavelength - 6562.8) ** 2) / (2 * 1.5**2)) + rng.normal(0, 0.01, 200)

    result = cross_correlate_radial_velocity(
        narrow_wavelength, narrow_flux, narrow_wavelength, narrow_flux,
        velocity_min_km_s=-50000.0, velocity_max_km_s=50000.0, velocity_step_km_s=5000.0,
    )
    assert np.any(np.isnan(result.correlation))
    assert not np.isnan(result.peak_correlation)  # el pico en sí debe caer en una velocidad con solape real


def test_cross_correlation_raises_when_nothing_overlaps_at_all():
    template_wavelength = np.linspace(4000.0, 5000.0, 500)
    template_flux = np.ones(500)
    observed_wavelength = np.linspace(9000.0, 9500.0, 500)  # rango completamente distinto
    observed_flux = np.ones(500)

    with pytest.raises(ValueError, match="solape"):
        cross_correlate_radial_velocity(
            observed_wavelength, observed_flux, template_wavelength, template_flux,
            velocity_min_km_s=-100.0, velocity_max_km_s=100.0, velocity_step_km_s=10.0,
        )


def test_cross_correlation_rejects_mismatched_shapes():
    with pytest.raises(ValueError):
        cross_correlate_radial_velocity(np.zeros(10), np.zeros(5), np.zeros(10), np.zeros(10))


def test_cross_correlation_rejects_bad_velocity_range():
    a = np.linspace(4000, 5000, 100)
    with pytest.raises(ValueError):
        cross_correlate_radial_velocity(a, np.ones(100), a, np.ones(100), velocity_min_km_s=100.0, velocity_max_km_s=-100.0)
