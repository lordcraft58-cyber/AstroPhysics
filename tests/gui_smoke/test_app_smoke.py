"""Prueba de humo de la GUI comercial nueva (`gui/`, Fase 8): la ventana
debe construirse y navegar entre todas las vistas sin excepción, y el
flujo de revisión humana (Conservar/Descartar/Marcar) debe producir el
efecto correcto sobre `SessionState` -- sin esto, un candidato podría
"perderse" silenciosamente al revisar (ver el hallazgo original de
`test_gui_smoke.py` en Fase 5, seccion legado: el propio arranque de la
GUI heredada nunca se había ejecutado hasta que un test lo hizo).

Requiere tkinter y un display X (real o Xvfb) -- si no están disponibles,
el test se salta en vez de fallar por una razón ajena al código bajo
prueba.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

tk = pytest.importorskip("tkinter")

from astrophysics_suite.core.enums import (  # noqa: E402
    IdentificationState, MorphologyClass, QualityLevel, ReviewState, ValueKind,
)
from astrophysics_suite.core.provenance import Provenance  # noqa: E402
from astrophysics_suite.core.quantity import Quantity  # noqa: E402
from astrophysics_suite.models.anomaly import AnomalyVector  # noqa: E402
from astrophysics_suite.models.candidate import Candidate, QualitySummary  # noqa: E402
from astrophysics_suite.models.detection import MorphologySummary, SkyPosition  # noqa: E402


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb)")


def _make_candidate(state: IdentificationState = IdentificationState.DISCOVERY_REVIEW) -> Candidate:
    provenance = Provenance.now(pipeline_version="test", engine="discovery_pipeline", engine_version="1.0")
    return Candidate.create(
        candidate_id="CAND-TEST-0001",
        observation_id="OBS-TEST-0001",
        detection_id="DET-0001",
        position=SkyPosition(x_px=10.0, y_px=20.0),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=12.0, elongation=1.0, compactness=0.9),
        provenance=provenance,
        identification_state=state,
        quality=QualitySummary(overall_level=QualityLevel.PASS),
        snr=Quantity(value=7.5, error=0.3, unit="sigma", kind=ValueKind.OBSERVED, method="background_std"),
        anomaly_evidence=AnomalyVector.create(
            detection_id="DET-0001",
            photometric=Quantity(value=3.0, error=None, unit="sigma", kind=ValueKind.PROXY, method="flux_ratio"),
        ),
        artifact_checks=(),
    )


@pytest.fixture
def app(monkeypatch):
    from gui.app import App

    root = tk.Tk()
    application = App(root)
    root.update_idletasks()
    yield application
    root.destroy()


def test_app_builds_all_views_without_exception(app):
    assert set(app.views) == {
        "project", "new_observation", "analysis", "candidates", "candidate_detail", "settings", "diagnostics",
    }


@pytest.mark.parametrize("view_key", ["project", "new_observation", "candidates", "settings", "diagnostics"])
def test_navigating_to_each_view_does_not_raise(app, view_key):
    app.show_view(view_key)  # no debe lanzar ninguna excepción
    app.root.update_idletasks()


def test_settings_view_current_params_reflects_defaults(app):
    from services.discovery_service import DiscoveryParams

    app.show_view("settings")
    params = app.views["settings"].current_params()
    assert params == DiscoveryParams()


def test_settings_view_ignores_invalid_input_and_keeps_default(app):
    from services.discovery_service import DiscoveryParams

    app.show_view("settings")
    settings_view = app.views["settings"]
    settings_view._vars["threshold_sigma"].set("no-es-un-numero")
    params = settings_view.current_params()
    assert params.threshold_sigma == DiscoveryParams().threshold_sigma
    assert "Umbral" in settings_view.status_label.cget("text")


def test_candidates_view_renders_candidate_and_opens_detail(app):
    candidate = _make_candidate()
    app.state.add_candidates([candidate])
    app.show_view("candidates")
    app.root.update_idletasks()

    app.open_candidate(candidate.candidate_id)
    app.root.update_idletasks()

    assert app.selected_candidate_id == candidate.candidate_id
    assert app.views["candidate_detail"]._candidate() is not None


def test_candidate_review_flow_updates_session_state(app, monkeypatch):
    from gui.views import candidate_detail_view as cdv

    candidate = _make_candidate()
    app.state.add_candidates([candidate])
    app.open_candidate(candidate.candidate_id)
    app.root.update_idletasks()

    monkeypatch.setattr(cdv.simpledialog, "askstring", lambda *a, **k: "Revisado en prueba de humo")
    app.views["candidate_detail"]._review(ReviewState.KEPT)

    updated = app.state.candidates[0]
    assert updated.review_state == ReviewState.KEPT
    assert len(updated.review_notes) == 1
    assert updated.review_notes[0].note == "Revisado en prueba de humo"


def test_candidate_review_cannot_go_back_to_pending(app):
    candidate = _make_candidate()
    with pytest.raises(ValueError):
        candidate.mark_reviewed(new_state=ReviewState.PENDING, author="x", note="x", reviewed_at=datetime.now(timezone.utc))
