from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.models.project import Project


def test_project_roundtrip():
    p = Project.create(project_id="PRJ-0001", name="Veil Nebula survey", created_at=datetime(2026, 9, 16, tzinfo=timezone.utc))
    p = p.with_observation("OBS-0001").with_candidate("CAND-0001").with_candidate("CAND-0002")
    restored = Project.from_dict(p.to_dict())
    assert restored == p
    assert restored.candidate_ids == ("CAND-0001", "CAND-0002")


def test_project_is_immutable_and_deduplicates():
    p = Project.create(project_id="PRJ-0001", name="Test", created_at=datetime.now(timezone.utc))
    p2 = p.with_observation("OBS-0001")
    assert p.observation_ids == ()  # el original no cambia
    assert p2.observation_ids == ("OBS-0001",)
    p3 = p2.with_observation("OBS-0001")  # repetido: no duplica
    assert p3.observation_ids == ("OBS-0001",)
