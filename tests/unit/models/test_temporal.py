from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence


def test_temporal_evidence_roundtrip():
    ev = TemporalEvidence.create(
        detection_id="DET-0001",
        n_epochs=4,
        appearance_detected=False,
        variable_candidate=True,
        brightness_change=Quantity(value=0.8, error=0.1, unit="mag", kind=ValueKind.OBSERVED, method="linear_fit"),
        notes=("cambio consistente con variabilidad instrumental descartada",),
    )
    restored = TemporalEvidence.from_dict(ev.to_dict())
    assert restored == ev
    assert restored.variable_candidate is True


def test_motion_evidence_roundtrip():
    ev = MotionEvidence.create(
        detection_id="DET-0001",
        n_epochs_used=2,
        pm_total=Quantity(value=15.3, error=2.1, unit="mas/yr", kind=ValueKind.OBSERVED, method="one_to_one_match"),
        moving_source_candidate=True,
    )
    restored = MotionEvidence.from_dict(ev.to_dict())
    assert restored == ev
    assert restored.moving_source_candidate is True


def test_motion_evidence_defaults_to_not_moving():
    ev = MotionEvidence.create(detection_id="DET-0002", n_epochs_used=2)
    assert ev.moving_source_candidate is False
    assert ev.pm_total is None
