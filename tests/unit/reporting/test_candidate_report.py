"""`build_candidate_report` contra un `Candidate` REAL producido por
`run_generic_discovery` (mismo generador de campo que
`tests/unit/io/test_session_export.py`) -- confirma que las 13 secciones
reflejan de verdad lo que cada motor midió, incluida la mensajería
honesta NO DISPONIBLE cuando un motor no corrió, nunca un valor inventado."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import numpy as np

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.discovery.pipeline import run_generic_discovery
from astrophysics_suite.io.fits_loader import build_observation
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.reporting.candidate_report import ANOMALY_DIMENSIONS, ANOMALY_LABELS, build_candidate_report
from astrophysics_suite.temporal.motion import analyze_motion
from astrophysics_suite.temporal.variability import analyze_variability
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _real_candidate(tmp_path):
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:120, 0:120]
    field = np.full((120, 120), 100.0, dtype=np.float32)
    for x, y in [(30, 30), (70, 80), (95, 40)]:
        field += 1200.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, field.shape)
    field = field.astype(np.float32)

    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)
    observation, loaded = build_observation([(str(path), "HA")], observation_id="OBS-REPORT-0001", target_name="Campo de prueba")
    candidates, _summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)
    assert candidates, "la prueba necesita al menos un candidato real"
    return observation, candidates[0]


class _FakeTrack:
    def __init__(self, positions):
        self._positions = positions

    def sky_positions(self):
        return self._positions


def _candidate_with_full_evidence(tmp_path):
    """Mismo candidato real de `_real_candidate`, con evidencia temporal,
    de movimiento y de anomalía REAL adjunta (vía los motores reales) --
    para ejercitar las 13 secciones completas, no solo las que ya trae
    un candidato genérico de una sola imagen."""
    observation, candidate = _real_candidate(tmp_path)

    rng = np.random.default_rng(7)
    epochs = [{"time": i * 1.3, "value": 1000.0 + 15.0 * i + rng.normal(0, 8.0), "error": 8.0} for i in range(8)]
    temporal_ev = analyze_variability(epochs, detection_id=candidate.candidate_id, pipeline_version="v-report-test")

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    positions = [(t0 + timedelta(hours=i * 2.0), 10.6847 + i * 0.0005, 41.2687 + i * 0.0002) for i in range(6)]
    motion_ev = analyze_motion(_FakeTrack(positions), detection_id=candidate.candidate_id, pipeline_version="v-report-test")

    anomaly_vec = AnomalyVector.create(
        detection_id=candidate.candidate_id,
        photometric=Quantity(value=5.2, error=0.4, unit="sigma", kind=ValueKind.PROXY, method="flux_zscore"),
        temporal=Quantity(value=6.8, error=0.5, unit="sigma", kind=ValueKind.PROXY, method="slope_significance"),
    )

    candidate = dataclasses.replace(candidate, temporal_evidence=temporal_ev, motion_evidence=motion_ev, anomaly_evidence=anomaly_vec)
    return observation, candidate


def test_build_candidate_report_produces_thirteen_ordered_sections(tmp_path):
    observation, candidate = _real_candidate(tmp_path)
    report = build_candidate_report(candidate, observation=observation, pipeline_version="v-report-test")

    assert len(report.sections) == 13
    assert report.subject_id == candidate.candidate_id
    assert [s.key for s in report.sections] == [
        "observation", "quality", "astrometry", "photometry", "morphology", "temporal", "motion",
        "physical", "anomaly", "evidence", "catalogs", "provenance", "review",
    ]


def test_observation_section_reflects_the_real_attached_observation(tmp_path):
    observation, candidate = _real_candidate(tmp_path)
    report = build_candidate_report(candidate, observation=observation, pipeline_version="v-report-test")

    section = report.section("observation")
    values = {f.label: f.value for f in section.fields}
    assert values["Objetivo"] == observation.target_name
    assert len(section.tables) == 1
    assert section.tables[0].rows[0][0] == observation.images[0].path


def test_observation_section_is_honestly_unavailable_without_an_observation(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("observation")
    assert section.fields[0].available is False
    assert "NO DISPONIBLE" in section.fields[0].value


def test_quality_section_reflects_real_snr_and_fwhm(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("quality")
    values = {f.label: f.value for f in section.fields}
    assert values["S/N"] != "NO DISPONIBLE"
    assert values["FWHM"] != "NO DISPONIBLE"


def test_astrometry_section_is_honestly_unavailable_without_wcs(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    assert not candidate.position.has_sky_coordinates
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("astrometry")
    values = {f.label: f.value for f in section.fields}
    assert "NO DISPONIBLE" in values["RA/Dec"]


def test_temporal_section_produces_a_real_light_curve_series_with_full_evidence(tmp_path):
    _observation, candidate = _candidate_with_full_evidence(tmp_path)
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("temporal")
    assert len(section.series) == 1
    series = section.series[0]
    assert series.kind == "line"
    assert len(series.x) == len(candidate.temporal_evidence.epochs)
    assert series.y_error is not None


def test_motion_section_produces_a_real_trajectory_series_with_full_evidence(tmp_path):
    _observation, candidate = _candidate_with_full_evidence(tmp_path)
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("motion")
    assert len(section.series) == 1
    series = section.series[0]
    assert series.kind == "scatter"
    assert len(series.x) == len(candidate.motion_evidence.epochs)


def test_anomaly_section_produces_a_bar_series_only_for_available_dimensions(tmp_path):
    _observation, candidate = _candidate_with_full_evidence(tmp_path)
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("anomaly")
    assert len(section.series) == 1
    series = section.series[0]
    assert series.kind == "bar"
    n_available = len(candidate.anomaly_evidence.flagged_dimensions)
    assert len(series.x) == n_available
    assert series.x_categories == tuple(ANOMALY_LABELS[n] for n in ANOMALY_DIMENSIONS if n in candidate.anomaly_evidence.flagged_dimensions)


def test_anomaly_section_has_no_series_when_no_dimension_is_available(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    assert candidate.anomaly_evidence is None or not candidate.anomaly_evidence.flagged_dimensions
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("anomaly")
    assert section.series == ()


def test_temporal_and_motion_sections_are_honestly_unavailable_without_evidence(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    assert candidate.temporal_evidence is None
    assert candidate.motion_evidence is None
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    for key in ("temporal", "motion"):
        section = report.section(key)
        assert section.series == ()
        assert section.fields[0].available is False


def test_physical_section_is_honestly_unavailable_in_generic_mode(tmp_path):
    _observation, candidate = _real_candidate(tmp_path)
    assert candidate.physical_evidence is None
    report = build_candidate_report(candidate, pipeline_version="v-report-test")

    section = report.section("physical")
    assert section.fields[0].available is False
    assert "genérico" in section.fields[0].value


def test_review_section_reflects_review_history(tmp_path):
    from astrophysics_suite.core.enums import ReviewState

    _observation, candidate = _real_candidate(tmp_path)
    reviewed = candidate.mark_reviewed(
        new_state=ReviewState.KEPT, author="Prueba", note="conservado en prueba", reviewed_at=datetime.now(timezone.utc)
    )
    report = build_candidate_report(reviewed, pipeline_version="v-report-test")

    section = report.section("review")
    values = {f.label: f.value for f in section.fields}
    assert values["Estado de revisión"] == "KEPT"
    assert len(section.tables) == 1
    assert section.tables[0].rows[0][0] == "Prueba"
