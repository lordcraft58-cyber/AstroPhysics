"""`reference_star_calibration.py` (§13): infiere una calibración
PROVISIONAL de longitud de onda a partir de líneas reales de una
estrella de referencia -- reutiliza detección/emparejamiento/ajuste ya
probados, nunca duplica esa física."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource
from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES
from astrophysics_suite.spectroscopy.reference_star_calibration import calibrate_from_reference_star


def _synthetic_star_spectrum(*, true_wave0=4000.0, true_dispersion=2.0, width=2000, sigma_px=2.5, depth=40.0, seed=3):
    rng = np.random.default_rng(seed)
    pixel = np.arange(width, dtype=np.float64)
    wavelength_true = true_wave0 + true_dispersion * pixel
    continuum = np.full(width, 200.0)
    flux = continuum.copy()
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - true_wave0) / true_dispersion
        if 0 <= true_pixel < width:
            flux -= depth * np.exp(-((pixel - true_pixel) ** 2) / (2 * sigma_px**2))
    flux += rng.normal(0, 0.3, width)
    return pixel, flux, continuum, wavelength_true


def test_calibrate_from_reference_star_recovers_a_known_dispersion():
    pixel, flux, continuum, wavelength_true = _synthetic_star_spectrum()
    true_wave0, true_dispersion = 4000.0, 2.0

    record = calibrate_from_reference_star(
        pixel, flux, continuum, BALMER_LINES,
        approx_dispersion_angstrom_per_px=true_dispersion * 1.01,  # aproximada, no exacta (1% de error)
        approx_wavelength_at_pixel0=true_wave0 + 10.0,  # aproximada, no exacta
        tolerance_angstrom=40.0, reference_object="Vega (sintética, A0V)", degree=1,
    )

    assert record.source is CalibrationSource.REFERENCE_STAR
    assert record.reference_object == "Vega (sintética, A0V)"
    assert record.n_lines_used >= 2
    # recupera la dispersión real dentro de un margen razonable frente al ruido/aproximación
    assert record.solution.pixel_to_wavelength(0.0) == pytest.approx(true_wave0, abs=5.0)
    assert record.solution.pixel_to_wavelength(1000.0) == pytest.approx(true_wave0 + true_dispersion * 1000.0, abs=5.0)


def test_calibrate_from_reference_star_provenance_warns_about_reference_star_source():
    from astrophysics_suite.spectroscopy.calibration_provenance import build_wavelength_provenance

    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    record = calibrate_from_reference_star(
        pixel, flux, continuum, BALMER_LINES,
        approx_dispersion_angstrom_per_px=2.02, approx_wavelength_at_pixel0=4010.0,
        tolerance_angstrom=40.0, reference_object="Vega (sintética, A0V)", degree=1,
    )
    provenance = build_wavelength_provenance(record)
    assert any("estrella de referencia" in w for w in provenance.warnings)
    assert not any("SIMULADA" in w for w in provenance.warnings)  # no es sintética: hay evidencia real detrás


def test_calibrate_from_reference_star_rejects_an_empty_reference_object():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    with pytest.raises(ValueError, match="reference_object"):
        calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES,
            approx_dispersion_angstrom_per_px=2.0, approx_wavelength_at_pixel0=4000.0,
            tolerance_angstrom=15.0, reference_object="   ",
        )


def test_calibrate_from_reference_star_raises_honestly_when_nothing_matches():
    pixel = np.arange(200, dtype=np.float64)
    flux = np.full(200, 100.0)  # continuo puro plano, sin ninguna línea real
    continuum = flux.copy()
    with pytest.raises(ValueError):
        calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES,
            approx_dispersion_angstrom_per_px=1.0, approx_wavelength_at_pixel0=4000.0,
            tolerance_angstrom=3.0, reference_object="estrella de prueba",
        )


def test_calibrate_from_reference_star_raises_when_too_few_lines_match_the_requested_degree():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    with pytest.raises(ValueError, match="grado"):
        calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES,
            approx_dispersion_angstrom_per_px=2.0, approx_wavelength_at_pixel0=4000.0,
            tolerance_angstrom=15.0, reference_object="estrella de prueba", degree=5,  # 4 lineas de Balmer, grado imposible
        )
