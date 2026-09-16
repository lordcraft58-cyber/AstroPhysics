from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.core.enums import IdentificationState, MorphologyClass, QualityLevel, ReviewState
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.candidate import Candidate, QualitySummary
from astrophysics_suite.models.detection import MorphologySummary, SkyPosition
from astrophysics_suite.models.observation import Observation
from services.session_state import SessionState


def _candidate(candidate_id: str) -> Candidate:
    return Candidate.create(
        candidate_id=candidate_id,
        observation_id="OBS-0001",
        detection_id="DET-0001",
        position=SkyPosition(x_px=1.0, y_px=1.0),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=10.0, elongation=1.0, compactness=0.5),
        quality=QualitySummary(overall_level=QualityLevel.PASS),
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
        identification_state=IdentificationState.DISCOVERY_REVIEW,
    )


def test_add_candidates_and_notify_listeners():
    state = SessionState()
    calls = []
    state.on_change(lambda: calls.append(1))

    state.add_candidates([_candidate("CAND-0001"), _candidate("CAND-0002")])

    assert len(state.candidates) == 2
    assert len(calls) == 1


def test_replace_candidate_preserves_list_order():
    state = SessionState()
    state.add_candidates([_candidate("CAND-0001"), _candidate("CAND-0002")])

    reviewed = state.candidates[0].mark_reviewed(
        new_state=ReviewState.KEPT, author="tester", note="ok", reviewed_at=datetime.now(timezone.utc)
    )
    state.replace_candidate(reviewed)

    assert state.candidates[0].review_state is ReviewState.KEPT
    assert state.candidates[0].candidate_id == "CAND-0001"
    assert state.candidates[1].review_state is ReviewState.PENDING


def test_candidates_pending_review():
    state = SessionState()
    state.add_candidates([_candidate("CAND-0001"), _candidate("CAND-0002")])
    reviewed = state.candidates[0].mark_reviewed(
        new_state=ReviewState.REJECTED, author="tester", note="artefacto", reviewed_at=datetime.now(timezone.utc)
    )
    state.replace_candidate(reviewed)

    pending = state.candidates_pending_review()
    assert len(pending) == 1
    assert pending[0].candidate_id == "CAND-0002"
