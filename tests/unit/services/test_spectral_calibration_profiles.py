"""`spectral_calibration_profiles.py`: perfiles de calibración
espectral persistentes (§12) -- reutilizables tal cual, o con SOLO el
desplazamiento global recalculado, nunca un reajuste completo sin
nueva evidencia, y nunca guardando una calibración SYNTHETIC como si
fuera una solución instrumental validada."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.calibration_provenance import (
    CalibrationSource,
    WavelengthCalibrationRecord,
    build_wavelength_provenance,
)
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
from services.spectral_calibration_profiles import (
    SpectralCalibrationProfile,
    SpectralCalibrationProfileStore,
    profile_from_record,
    reidentify_profile_offset,
)


def _lamp_record(n_lines=6, degree=1, seed=1):
    rng = np.random.default_rng(seed)
    pixels = np.sort(rng.uniform(20, 980, size=n_lines))
    wavelengths = 1.4 * pixels + 4500.0
    solution = fit_wavelength_solution(list(pixels), list(wavelengths), degree=degree)
    return WavelengthCalibrationRecord(solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=n_lines, lamp_name="Ne")


def _synthetic_arc_row(width=1000, *, true_pixels=(200.0, 500.0, 800.0), shift=0.0, seed=3):
    rng = np.random.default_rng(seed)
    row = np.full(width, 100.0) + rng.normal(0, 2.0, width)
    for p in true_pixels:
        idx = int(round(p + shift))
        row[idx - 2 : idx + 3] += np.array([80, 600, 1500, 600, 80])
    return row


def test_store_starts_empty_when_no_file_exists(tmp_path):
    store = SpectralCalibrationProfileStore(tmp_path / "profiles.json")
    assert store.load_all() == {}


def test_profile_from_record_round_trips_through_the_store(tmp_path):
    record = _lamp_record()
    reference_spectrum = _synthetic_arc_row()
    profile = profile_from_record("LHIRES III -- red 2400", record, reference_spectrum=reference_spectrum)
    store = SpectralCalibrationProfileStore(tmp_path / "profiles.json")

    store.save(profile)
    reloaded = store.load_all()["LHIRES III -- red 2400"]

    np.testing.assert_allclose(reloaded.coefficients, profile.coefficients)
    assert reloaded.degree == profile.degree
    assert reloaded.n_lines_used == profile.n_lines_used
    assert reloaded.lamp_name == "Ne"
    np.testing.assert_allclose(reloaded.reference_spectrum, reference_spectrum)


def test_profile_from_record_refuses_a_synthetic_calibration():
    synthetic_record = WavelengthCalibrationRecord(
        solution=_lamp_record().solution, source=CalibrationSource.SYNTHETIC, n_lines_used=6,
    )
    with pytest.raises(ValueError, match="SYNTHETIC"):
        profile_from_record("perfil de prueba", synthetic_record)


def test_to_record_marks_the_reused_solution_as_reused_instrumental_and_never_warns_by_itself():
    record = _lamp_record(n_lines=10, degree=1)
    profile = profile_from_record("Alpy 600", record)

    reused = profile.to_record()

    assert reused.source is CalibrationSource.REUSED_INSTRUMENTAL
    assert reused.is_measured
    assert not reused.offset_only_reidentified
    np.testing.assert_allclose(reused.solution.coefficients, record.solution.coefficients)
    assert build_wavelength_provenance(reused).warnings == ()


def test_reidentify_profile_offset_recovers_the_true_shift():
    record = _lamp_record(degree=1)
    reference_spectrum = _synthetic_arc_row(shift=0.0)
    profile = profile_from_record("eShel", record, reference_spectrum=reference_spectrum)

    true_shift = 4.3
    new_spectrum = _synthetic_arc_row(shift=true_shift)

    shifted_record = reidentify_profile_offset(profile, new_spectrum)

    assert shifted_record.source is CalibrationSource.REUSED_INSTRUMENTAL
    assert shifted_record.offset_only_reidentified
    assert shifted_record.solution.reference_pixel_shift == pytest.approx(true_shift, abs=0.5)
    # la forma del polinomio (coeficientes) no cambia, solo el desplazamiento
    np.testing.assert_allclose(shifted_record.solution.coefficients, record.solution.coefficients)


def test_reidentify_profile_offset_warns_about_possible_instrument_drift():
    record = _lamp_record(degree=1)
    reference_spectrum = _synthetic_arc_row(shift=0.0)
    profile = profile_from_record("eShel", record, reference_spectrum=reference_spectrum)

    shifted_record = reidentify_profile_offset(profile, _synthetic_arc_row(shift=2.0))
    warnings = build_wavelength_provenance(shifted_record).warnings

    assert any("deriva" in w or "mecánico" in w or "térmico" in w for w in warnings)


def test_reidentify_profile_offset_without_a_saved_reference_spectrum_raises():
    record = _lamp_record()
    profile = profile_from_record("sin espectro guardado", record)  # reference_spectrum=None

    with pytest.raises(ValueError, match="referencia"):
        reidentify_profile_offset(profile, _synthetic_arc_row())


def test_reidentify_profile_offset_rejects_a_mismatched_pixel_count():
    record = _lamp_record()
    profile = profile_from_record("perfil", record, reference_spectrum=_synthetic_arc_row(width=1000))

    with pytest.raises(ValueError, match="configuración"):
        reidentify_profile_offset(profile, _synthetic_arc_row(width=500, true_pixels=(100.0, 250.0, 400.0)))


def test_delete_removes_profile(tmp_path):
    store = SpectralCalibrationProfileStore(tmp_path / "profiles.json")
    store.save(SpectralCalibrationProfile(
        name="ToDelete", coefficients=(1.4, 4500.0), degree=1, rms_residual=0.1,
        reference_pixel_shift=0.0, n_lines_used=6,
    ))
    assert "ToDelete" in store.load_all()

    store.delete("ToDelete")

    assert "ToDelete" not in store.load_all()


def test_save_persists_across_new_store_instance_same_path(tmp_path):
    path = tmp_path / "profiles.json"
    profile = SpectralCalibrationProfile(
        name="Star Analyser", coefficients=(2.0, 4000.0), degree=1, rms_residual=0.2,
        reference_pixel_shift=0.0, n_lines_used=8, lamp_name="Ar",
    )
    SpectralCalibrationProfileStore(path).save(profile)

    reloaded = SpectralCalibrationProfileStore(path).load_all()

    assert "Star Analyser" in reloaded
    assert reloaded["Star Analyser"].lamp_name == "Ar"
