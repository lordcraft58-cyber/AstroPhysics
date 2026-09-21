"""`reference_star_calibration.py` (§13): infiere una calibración
PROVISIONAL de longitud de onda a partir de líneas reales de una
estrella de referencia -- reutiliza detección/emparejamiento/ajuste ya
probados, nunca duplica esa física."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, build_wavelength_provenance
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES
from astrophysics_suite.spectroscopy.reference_star_calibration import (
    blind_calibrate_from_reference_star,
    calibrate_from_reference_star,
)


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


def test_blind_calibrate_from_reference_star_recovers_a_known_dispersion_without_any_approximate_guess():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    true_wave0, true_dispersion = 4000.0, 2.0

    record = blind_calibrate_from_reference_star(
        pixel, flux, continuum, BALMER_LINES,
        tolerance_angstrom=5.0, reference_object="Vega (sintética, A0V)", degree=1,
    )

    assert record.source is CalibrationSource.REFERENCE_STAR
    assert record.blind_search is True
    assert record.n_lines_used >= 2
    assert record.solution.pixel_to_wavelength(0.0) == pytest.approx(true_wave0, abs=5.0)
    assert record.solution.pixel_to_wavelength(1000.0) == pytest.approx(true_wave0 + true_dispersion * 1000.0, abs=5.0)


def test_blind_calibrate_from_reference_star_provenance_warns_about_the_blind_search():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    record = blind_calibrate_from_reference_star(
        pixel, flux, continuum, BALMER_LINES,
        tolerance_angstrom=5.0, reference_object="Vega (sintética, A0V)", degree=1,
    )
    provenance = build_wavelength_provenance(record)
    assert any("búsqueda ciega" in w for w in provenance.warnings)
    assert any("estrella de referencia" in w for w in provenance.warnings)  # sigue llevando el aviso normal de REFERENCE_STAR


def test_blind_calibrate_from_reference_star_raises_honestly_when_nothing_matches():
    pixel = np.arange(200, dtype=np.float64)
    flux = np.full(200, 100.0)  # continuo puro plano, sin ninguna línea real
    continuum = flux.copy()
    with pytest.raises(ValueError):
        blind_calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES,
            tolerance_angstrom=3.0, reference_object="estrella de prueba",
        )


def test_blind_calibrate_from_reference_star_raises_when_too_few_detections_for_real_evidence():
    # degree + 1 (dos puntos, para grado 1) SIEMPRE encaja exactamente con
    # cualquier asignación de catálogo -- no es evidencia real sin un
    # tercer punto que corrobore (degree + 2, tres para grado 1).
    pixel = np.arange(400, dtype=np.float64)
    continuum = np.full(400, 200.0)
    flux = continuum.copy()
    flux -= 60.0 * np.exp(-((pixel - 150.0) ** 2) / (2 * 2.5**2))
    with pytest.raises(ValueError, match="al menos 3"):
        blind_calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES,
            tolerance_angstrom=5.0, reference_object="estrella de prueba",
        )


def test_blind_calibrate_from_reference_star_rejects_an_empty_reference_object():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    with pytest.raises(ValueError, match="reference_object"):
        blind_calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES, tolerance_angstrom=5.0, reference_object="   ",
        )


def test_blind_calibrate_from_reference_star_never_trusts_a_two_point_fit_over_a_real_three_point_one():
    # Hallazgo real (validado con un espectro real de T-CrB): con
    # exactamente degree+1 puntos (dos, para grado 1), SIEMPRE existe una
    # transformación que los hace encajar exactamente, para CUALQUIER
    # asignación de catálogo -- residuo cero por construcción, no por
    # evidencia real. Aquí se construyen dos parejas reales de picos: una
    # débil (pero con una asignación de catálogo EXACTA, residuo 0) y
    # otra fuerte (con una asignación real pero desplazada 0.4 px, residuo
    # pequeño pero no nulo). Sin exigir un tercer punto real, la pareja
    # débil-pero-exacta podía ganar solo por tener menor residuo.
    width = 1400
    pixel = np.arange(width, dtype=np.float64)
    rng = np.random.default_rng(0)
    continuum = np.full(width, 500.0)
    flux = continuum + rng.normal(0, 1.0, width)

    def bump(center_px, depth, sigma=1.5):
        xs = np.arange(max(0, int(center_px) - 8), min(width, int(center_px) + 9))
        flux[xs] += depth * np.exp(-0.5 * ((xs - center_px) / sigma) ** 2)

    h_alpha = next(line for line in BALMER_LINES if line.label == "H-alpha")
    h_beta = next(line for line in BALMER_LINES if line.label == "H-beta")
    h_gamma = next(line for line in BALMER_LINES if line.label == "H-gamma")
    h_delta = next(line for line in BALMER_LINES if line.label == "H-delta")

    # pareja real fuerte (Ha/Hb), colocada 0.4 px fuera de la predicción exacta
    px_alpha_true, px_beta_true = 1200.0, 400.0
    bump(px_alpha_true + 0.4, depth=100.0)
    bump(px_beta_true + 0.4, depth=100.0)

    # pareja real débil (Hg/Hd), colocada EXACTAMENTE en la predicción (residuo 0)
    px_gamma_true, px_delta_true = 300.0, 100.0
    bump(px_gamma_true, depth=15.0)
    bump(px_delta_true, depth=15.0)

    continuum_fit = fit_continuum(pixel, flux, degree=1, sigma_clip=2.5)

    with pytest.raises(ValueError, match="al menos 3"):
        # con solo estas 4 detecciones reales, ninguna combinación real
        # alcanza degree+2=3 coincidencias con el catálogo Balmer --
        # exactamente el comportamiento honesto que se quiere: ni la
        # pareja débil-exacta ni la fuerte-desplazada se aceptan solas.
        blind_calibrate_from_reference_star(
            pixel, flux, continuum_fit.continuum, BALMER_LINES,
            tolerance_angstrom=5.0, reference_object="TEST", degree=1,
        )


def test_blind_calibrate_from_reference_star_rejects_an_invalid_dispersion_range():
    pixel, flux, continuum, _wavelength_true = _synthetic_star_spectrum()
    with pytest.raises(ValueError, match="dispersion_angstrom_per_px"):
        blind_calibrate_from_reference_star(
            pixel, flux, continuum, BALMER_LINES, tolerance_angstrom=5.0, reference_object="estrella de prueba",
            min_dispersion_angstrom_per_px=10.0, max_dispersion_angstrom_per_px=1.0,
        )
