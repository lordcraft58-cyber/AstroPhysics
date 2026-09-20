"""`calibration_provenance.py`: nunca presentar una calibración
inventada como medida de una observación real (§11/§41)."""
from __future__ import annotations

import numpy as np

from astrophysics_suite.spectroscopy.calibration_provenance import (
    MIN_LINES_PER_DEGREE,
    CalibrationSource,
    WavelengthCalibrationRecord,
    build_wavelength_provenance,
)
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution


def _solution(n_lines: int, degree: int, seed: int = 0):
    rng = np.random.default_rng(seed)
    pixels = np.sort(rng.uniform(50, 950, size=n_lines))
    true_wl = 1.4 * pixels + 4500.0
    noisy_wl = true_wl + rng.normal(0, 0.02, size=n_lines)
    return fit_wavelength_solution(list(pixels), list(noisy_wl), degree=degree)


def test_synthetic_source_is_never_measured_and_always_warns():
    record = WavelengthCalibrationRecord(solution=_solution(6, 1), source=CalibrationSource.SYNTHETIC, n_lines_used=6)
    assert record.is_synthetic
    assert not record.is_measured
    provenance = build_wavelength_provenance(record)
    assert any("SIMULADA" in w for w in provenance.warnings)


def test_lamp_real_source_is_measured_and_does_not_warn_about_being_synthetic():
    record = WavelengthCalibrationRecord(
        solution=_solution(12, 3), source=CalibrationSource.LAMP_REAL, n_lines_used=12, lamp_name="Ne",
    )
    assert record.is_measured
    assert not record.is_synthetic
    provenance = build_wavelength_provenance(record)
    assert not any("SIMULADA" in w for w in provenance.warnings)
    assert provenance.warnings == ()


def test_reference_star_source_always_warns_about_being_provisional():
    record = WavelengthCalibrationRecord(
        solution=_solution(8, 2), source=CalibrationSource.REFERENCE_STAR, n_lines_used=8, reference_object="Vega",
    )
    provenance = build_wavelength_provenance(record)
    assert any("velocidad radial" in w for w in provenance.warnings)


def test_too_few_lines_for_the_degree_is_flagged_with_the_measured_threshold():
    """Medido, no supuesto: ver el docstring de MIN_LINES_PER_DEGREE --
    con exactamente grado+1 líneas el ajuste interpola y el RMS
    declarado no mide nada."""
    degree = 3
    minimal_record = WavelengthCalibrationRecord(
        solution=_solution(degree + 1, degree), source=CalibrationSource.LAMP_REAL, n_lines_used=degree + 1,
    )
    warnings = build_wavelength_provenance(minimal_record).warnings
    assert any("grados de libertad" in w for w in warnings)

    comfortable_record = WavelengthCalibrationRecord(
        solution=_solution(degree * MIN_LINES_PER_DEGREE + 4, degree),
        source=CalibrationSource.LAMP_REAL, n_lines_used=degree * MIN_LINES_PER_DEGREE + 4,
    )
    assert build_wavelength_provenance(comfortable_record).warnings == ()


def test_describe_lists_only_what_is_really_known():
    record = WavelengthCalibrationRecord(
        solution=_solution(10, 2), source=CalibrationSource.LAMP_REAL, n_lines_used=10, n_lines_rejected=2, lamp_name="Ar",
    )
    described = " ".join(record.describe())
    assert "lámpara de calibración real" in described
    assert "Ar" in described
    assert "10" in described and "2" in described


def test_reused_instrumental_source_is_measured():
    record = WavelengthCalibrationRecord(
        solution=_solution(10, 1), source=CalibrationSource.REUSED_INSTRUMENTAL, n_lines_used=10,
    )
    assert record.is_measured
    assert build_wavelength_provenance(record).warnings == ()
