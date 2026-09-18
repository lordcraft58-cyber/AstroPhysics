"""`build_observation_report` contra candidatos REALES producidos por
`run_generic_discovery` -- confirma que cada número agregado (conteos
por estado, dimensiones de anomalía, gate científico) refleja de
verdad los candidatos recibidos, nunca un valor inventado o una media
sobre datos que no llegaron."""
from __future__ import annotations

import dataclasses

import numpy as np

from astrophysics_suite.core.enums import ReviewState, ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.discovery.pipeline import run_generic_discovery
from astrophysics_suite.io.fits_loader import build_observation
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.reporting.observation_report import build_observation_report
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _real_observation_and_candidates(tmp_path):
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:120, 0:120]
    field = np.full((120, 120), 100.0, dtype=np.float32)
    for x, y in [(30, 30), (70, 80), (95, 40)]:
        field += 1200.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, field.shape)
    field = field.astype(np.float32)

    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)
    observation, loaded = build_observation([(str(path), "HA")], observation_id="OBS-AGG-0001", target_name="Campo agregado")
    candidates, _summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)
    assert len(candidates) >= 2, "la prueba necesita varios candidatos reales para que los agregados tengan sentido"
    return observation, candidates


def test_summary_section_counts_real_candidates_by_identification_state(tmp_path):
    observation, candidates = _real_observation_and_candidates(tmp_path)
    report = build_observation_report(observation, candidates, pipeline_version="v-obs-report-test")

    summary = report.section("summary")
    values = {f.label: f.value for f in summary.fields}
    assert values["Candidatos totales"] == str(len(candidates))
    assert values["Objetivo"] == observation.target_name

    state_table = summary.tables[0]
    assert sum(row[1] for row in state_table.rows) == len(candidates)
    real_states = {c.identification_state.value for c in candidates}
    assert {row[0] for row in state_table.rows} == real_states


def test_summary_section_counts_real_review_state_changes(tmp_path):
    observation, candidates = _real_observation_and_candidates(tmp_path)
    reviewed = candidates[0].mark_reviewed(new_state=ReviewState.KEPT, author="Prueba", note="ok", reviewed_at=observation.created_at)
    updated = [reviewed] + list(candidates[1:])

    report = build_observation_report(observation, updated, pipeline_version="v-obs-report-test")
    review_table = report.section("summary").tables[1]
    review_counts = dict(review_table.rows)
    assert review_counts.get("KEPT") == 1
    assert review_counts.get("PENDING", 0) == len(candidates) - 1


def test_observation_section_is_honestly_unavailable_without_an_observation(tmp_path):
    _observation, candidates = _real_observation_and_candidates(tmp_path)
    report = build_observation_report(None, candidates, pipeline_version="v-obs-report-test")

    summary = report.section("summary")
    values = {f.label: f.value for f in summary.fields}
    assert values["Observación"] == "NO DISPONIBLE (no se adjuntó al generar el informe)"
    assert report.subject_id == "(sin observación adjunta)"


def test_anomaly_section_aggregates_real_dimensions_across_candidates(tmp_path):
    observation, candidates = _real_observation_and_candidates(tmp_path)
    with_anomaly = [
        dataclasses.replace(c, anomaly_evidence=AnomalyVector.create(
            detection_id=c.candidate_id,
            photometric=Quantity(value=3.0 + i, error=0.2, unit="sigma", kind=ValueKind.PROXY, method="flux_zscore"),
        ))
        for i, c in enumerate(candidates)
    ]
    report = build_observation_report(observation, with_anomaly, pipeline_version="v-obs-report-test")

    section = report.section("anomaly")
    values = {f.label: f.value for f in section.fields}
    assert f"{len(with_anomaly)} candidato(s)" in values["Fotométrica"]
    max_value = max(3.0 + i for i in range(len(with_anomaly)))
    assert f"máx {max_value:.4g}" in values["Fotométrica"]
    assert len(section.series) == 1
    assert section.series[0].kind == "bar"


def test_anomaly_section_is_honestly_unavailable_without_any_anomaly_evidence(tmp_path):
    observation, candidates = _real_observation_and_candidates(tmp_path)
    without_anomaly = [dataclasses.replace(c, anomaly_evidence=None) for c in candidates]
    report = build_observation_report(observation, without_anomaly, pipeline_version="v-obs-report-test")

    section = report.section("anomaly")
    assert section.series == ()
    assert section.fields[0].available is False


def test_evidence_section_counts_real_scientific_gate_and_ranks_by_priority(tmp_path):
    observation, candidates = _real_observation_and_candidates(tmp_path)
    with_chain = [c for c in candidates if c.evidence_chain is not None]

    report = build_observation_report(observation, candidates, pipeline_version="v-obs-report-test")
    section = report.section("evidence")
    values = {f.label: f.value for f in section.fields}
    assert values["Candidatos con cadena de evidencia"] == str(len(with_chain))

    real_gate_count = sum(1 for c in with_chain if c.evidence_chain.scientific_candidate_gate)
    assert values["Superan el gate científico (>= evidencia mínima)"] == str(real_gate_count)

    if with_chain:
        table = section.tables[0]
        priorities = [row[2] for row in table.rows]
        assert priorities == sorted(priorities, reverse=True)


def test_empty_candidate_list_stays_honest_everywhere():
    report = build_observation_report(None, [], pipeline_version="v-obs-report-test")

    summary_values = {f.label: f.value for f in report.section("summary").fields}
    assert summary_values["Candidatos totales"] == "0"
    assert report.section("quality").fields[0].available is False
