"""Prueba end-to-end del job en hilo de fondo contra FITS sintéticos
reales -- confirma que la GUI puede consumir progreso/resultado sin
bloquear, y que cancelar de verdad detiene el trabajo."""
from __future__ import annotations

import time

import numpy as np

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
from services.discovery_service import DiscoveryJob, DiscoveryParams


def _star_field(shape, positions, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, 100.0, dtype=np.float32)
    for x, y in positions:
        field += 900.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def _wait_for_events(job: DiscoveryJob, kinds: set[str], timeout: float = 10.0) -> list:
    collected = []
    deadline = time.monotonic() + timeout
    seen_kinds = set()
    while time.monotonic() < deadline:
        events = job.poll()
        collected.extend(events)
        seen_kinds.update(e.kind for e in events)
        if seen_kinds & kinds:
            return collected
        time.sleep(0.02)
    raise AssertionError(f"Timeout esperando eventos {kinds}; vistos: {seen_kinds}")


def test_discovery_job_runs_in_background_and_reports_progress(tmp_path):
    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)

    job = DiscoveryJob(target_name="Campo de prueba", images=[(str(path), "OIII")], params=DiscoveryParams(threshold_sigma=4.0))
    job.start()

    events = _wait_for_events(job, {"done", "error"})
    kinds = [e.kind for e in events]
    assert "progress" in kinds, "debe reportar progreso antes de terminar"
    assert kinds[-1] == "done"

    done_event = events[-1]
    assert done_event.observation is not None
    assert done_event.summary is not None
    assert done_event.summary.n_detected >= 2
    assert len(done_event.candidates) == done_event.summary.n_candidates


def test_discovery_job_cancel_stops_before_completion(tmp_path):
    field = _star_field((96, 96), [(30, 30)])
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)

    job = DiscoveryJob(target_name="Campo cancelado", images=[(str(path), "HA")])
    job.cancel()  # cancelar antes de start(): debe detenerse en el primer chequeo
    job.start()

    events = _wait_for_events(job, {"cancelled", "done", "error"})
    assert events[-1].kind == "cancelled"
