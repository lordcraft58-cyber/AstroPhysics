"""Integración de punta a punta del motor de visualización e informes:
`Candidate` real (producido por `run_generic_discovery`, con evidencia
temporal/de movimiento/de anomalía real adjunta) -> `build_candidate_report`
-> `render_html`/`export_html`, confirmando que el archivo final trae
las 13 secciones, las tres gráficas reales embebidas y ningún valor
inventado -- la misma cadena que ejercita el botón "Generar informe
científico..." de la GUI."""
from __future__ import annotations

import dataclasses
from datetime import datetime, timedelta, timezone

import numpy as np

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.discovery.pipeline import run_generic_discovery
from astrophysics_suite.export.html import export_html, render_html
from astrophysics_suite.io.fits_loader import build_observation
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.reporting.candidate_report import build_candidate_report
from astrophysics_suite.temporal.motion import analyze_motion
from astrophysics_suite.temporal.variability import analyze_variability
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


class _FakeTrack:
    def __init__(self, positions):
        self._positions = positions

    def sky_positions(self):
        return self._positions


def _full_candidate_and_observation(tmp_path):
    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:120, 0:120]
    field = np.full((120, 120), 100.0, dtype=np.float32)
    for x, y in [(30, 30), (70, 80), (95, 40)]:
        field += 1200.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, field.shape)
    field = field.astype(np.float32)

    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)
    observation, loaded = build_observation([(str(path), "HA")], observation_id="OBS-PIPELINE-0001", target_name="Campo integración")
    candidates, _summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)
    assert candidates
    candidate = candidates[0]

    epochs = [{"time": i * 1.3, "value": 1000.0 + 15.0 * i + rng.normal(0, 8.0), "error": 8.0} for i in range(8)]
    temporal_ev = analyze_variability(epochs, detection_id=candidate.candidate_id, pipeline_version="v-pipeline-test")

    t0 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    positions = [(t0 + timedelta(hours=i * 2.0), 10.6847 + i * 0.0005, 41.2687 + i * 0.0002) for i in range(6)]
    motion_ev = analyze_motion(_FakeTrack(positions), detection_id=candidate.candidate_id, pipeline_version="v-pipeline-test")

    anomaly_vec = AnomalyVector.create(
        detection_id=candidate.candidate_id,
        photometric=Quantity(value=5.2, error=0.4, unit="sigma", kind=ValueKind.PROXY, method="flux_zscore"),
        morphological=Quantity(value=2.1, error=0.3, unit="sigma", kind=ValueKind.PROXY, method="fwhm_zscore"),
        temporal=Quantity(value=6.8, error=0.5, unit="sigma", kind=ValueKind.PROXY, method="slope_significance"),
    )
    candidate = dataclasses.replace(candidate, temporal_evidence=temporal_ev, motion_evidence=motion_ev, anomaly_evidence=anomaly_vec)
    return observation, candidate


def test_full_candidate_to_html_report_pipeline_produces_a_real_self_contained_file(tmp_path):
    observation, candidate = _full_candidate_and_observation(tmp_path)

    report = build_candidate_report(candidate, observation=observation, pipeline_version="v-pipeline-test")
    assert len(report.sections) == 13

    n_series = sum(len(s.series) for s in report.sections)
    assert n_series == 3, "curva de luz + trayectoria + vector de anomalía"

    html_text = render_html(report)
    assert html_text.count("data:image/png;base64,") == 3
    assert candidate.candidate_id in html_text
    assert "NO DISPONIBLE" in html_text  # secciones honestas (astrometría/física sin datos) siguen presentes

    out_path = tmp_path / "informe.html"
    export_html(report, str(out_path))
    assert out_path.exists()
    assert out_path.read_text(encoding="utf-8") == html_text
    assert out_path.stat().st_size > 50_000


def test_full_pipeline_report_reflects_the_same_candidate_produced_by_discovery(tmp_path):
    observation, candidate = _full_candidate_and_observation(tmp_path)
    report = build_candidate_report(candidate, observation=observation, pipeline_version="v-pipeline-test")

    quality_values = {f.label: f.value for f in report.section("quality").fields}
    assert quality_values["S/N"].startswith(f"{candidate.snr.value:.4g}")

    temporal_series = report.section("temporal").series[0]
    assert temporal_series.x == tuple(e.time for e in candidate.temporal_evidence.epochs)

    motion_series = report.section("motion").series[0]
    assert motion_series.x == tuple(e.ra_deg for e in candidate.motion_evidence.epochs)
