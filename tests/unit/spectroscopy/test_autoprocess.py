"""`autoprocess.py` (§34): encadena traza -> extracción -> calibración
por estrella de referencia (§13) -> identificación de líneas -> informe
de calidad (§31/§42) reutilizando los motores ya probados por separado
en `test_trace.py`/`test_reference_star_calibration.py`/`test_qc_report.
py` -- aquí solo se comprueba la ORQUESTACIÓN (qué paso corre, se omite
o falla, y con qué motivo real), nunca la física de cada motor."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.autoprocess import run_autoprocess_spectrum
from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES
from astrophysics_suite.spectroscopy.qc_report import QCStatus
from astrophysics_suite.spectroscopy.trace import extract_optimal


def _synthetic_2d_star_frame(
    shape=(41, 2000), *, center=20.0, sigma=2.0, wave0=4000.0, dispersion=2.0,
    continuum=6000.0, depth=1200.0, line_sigma_px=2.5, background=50.0, seed=11,
):
    """Fotograma 2D real: perfil espacial gaussiano normalizado (misma
    forma que `test_trace._synthetic_2d_spectrum`) multiplicado por un
    espectro 1D con depresiones reales de Balmer en las columnas que les
    corresponden según `wave0`/`dispersion` (misma idea que
    `test_reference_star_calibration._synthetic_star_spectrum`, aquí
    extendida a 2D para poder pasar por `trace_spectrum`/`extract_*`
    antes de la calibración)."""
    rng = np.random.default_rng(seed)
    height, width = shape
    pixel = np.arange(width, dtype=np.float64)
    flux_per_col = np.full(width, continuum)
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - wave0) / dispersion
        if 0 <= true_pixel < width:
            flux_per_col -= depth * np.exp(-((pixel - true_pixel) ** 2) / (2 * line_sigma_px**2))
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - center) ** 2) / (2 * sigma**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = background + flux_per_col[np.newaxis, :] * profile
    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data, uncertainty


_NO_BAD_PIXELS = np.zeros((41, 2000), dtype=np.uint16)


def _step(result, name):
    return next(s for s in result.steps if s.name == name)


def test_run_autoprocess_spectrum_completes_the_full_chain_and_recovers_a_known_calibration():
    wave0, dispersion = 4000.0, 2.0
    data, uncertainty = _synthetic_2d_star_frame(wave0=wave0, dispersion=dispersion)

    result = run_autoprocess_spectrum(
        data, uncertainty, initial_center_px=20.0,
        quality_mask=_NO_BAD_PIXELS, saturate_available=False,
        extractor=extract_optimal, extraction_method_label="óptima (Horne 1986)",
        calibration_catalog=BALMER_LINES, identify_catalog=BALMER_LINES,
        approx_dispersion_angstrom_per_px=dispersion * 1.01, approx_wavelength_at_pixel0=wave0 + 10.0,
        calibration_tolerance_angstrom=40.0, identify_tolerance_angstrom=40.0,
    )

    assert [s.status for s in result.steps] == ["ok", "ok", "ok", "ok", "ok"]
    assert result.overall_ok is True
    assert result.wavelength_solution is not None
    assert result.calibration_record is not None
    assert result.calibration_record.n_lines_used >= 2
    assert result.wavelength_solution.pixel_to_wavelength(0.0) == pytest.approx(wave0, abs=5.0)
    assert len(result.line_matches) >= 2
    assert result.qc_report.overall_status is not QCStatus.ERROR
    # las seis filas del informe de calidad (§31/§42), todas con la misma
    # traza/extracción real que ya se hizo una sola vez para todo el autoproceso
    assert len(result.qc_report.metrics) == 6


def test_run_autoprocess_spectrum_skips_calibration_and_identification_when_disabled():
    data, uncertainty = _synthetic_2d_star_frame()

    result = run_autoprocess_spectrum(
        data, uncertainty, initial_center_px=20.0,
        quality_mask=_NO_BAD_PIXELS, saturate_available=False,
        extractor=extract_optimal, extraction_method_label="óptima (Horne 1986)",
        calibration_catalog=BALMER_LINES, identify_catalog=BALMER_LINES,
        calibrate_wavelength=False, identify_lines=True,
    )

    assert _step(result, "Traza espacial").status == "ok"
    assert _step(result, "Extracción").status == "ok"
    calibration_step = _step(result, "Calibración en longitud de onda (§13, provisional)")
    assert calibration_step.status == "omitido"
    assert "desactivada" in calibration_step.detail
    identification_step = _step(result, "Identificación de líneas")
    assert identification_step.status == "omitido"
    assert "necesita una calibración" in identification_step.detail
    assert result.wavelength_solution is None
    assert result.calibration_record is None
    assert result.line_matches == ()


def test_run_autoprocess_spectrum_reports_a_real_calibration_failure_without_losing_the_extraction():
    height, width = 41, 300
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - 20.0) ** 2) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    column = 50.0 + 4000.0 * profile  # continuo puro, sin ninguna línea real -> la calibración no tiene nada que emparejar
    data = np.tile(column, (1, width))
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    quality_mask = np.zeros(data.shape, dtype=np.uint16)

    result = run_autoprocess_spectrum(
        data, uncertainty, initial_center_px=20.0,
        quality_mask=quality_mask, saturate_available=False,
        extractor=extract_optimal, extraction_method_label="óptima (Horne 1986)",
        calibration_catalog=BALMER_LINES, identify_catalog=BALMER_LINES,
    )

    assert _step(result, "Traza espacial").status == "ok"
    assert _step(result, "Extracción").status == "ok"
    assert result.spectrum is not None
    calibration_step = _step(result, "Calibración en longitud de onda (§13, provisional)")
    assert calibration_step.status == "error"
    assert calibration_step.detail  # motivo real, nunca vacío
    identification_step = _step(result, "Identificación de líneas")
    assert identification_step.status == "omitido"
    assert result.overall_ok is False


def test_run_autoprocess_spectrum_propagates_a_real_trace_failure_instead_of_hiding_it():
    data = np.full((41, 100), 100.0)
    uncertainty = np.sqrt(data)
    with pytest.raises(ValueError):
        run_autoprocess_spectrum(
            data, uncertainty, initial_center_px=999.0,  # fuera de la imagen
            quality_mask=np.zeros(data.shape, dtype=np.uint16), saturate_available=False,
            extractor=extract_optimal, extraction_method_label="óptima (Horne 1986)",
            calibration_catalog=BALMER_LINES, identify_catalog=BALMER_LINES,
        )
