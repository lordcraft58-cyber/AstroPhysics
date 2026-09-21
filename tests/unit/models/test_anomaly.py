from __future__ import annotations

import pytest

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.anomaly import AnomalyVector


def _z(value: float, method: str = "robust_z_score") -> Quantity:
    return Quantity(value=value, error=None, unit="sigma", kind=ValueKind.OBSERVED, method=method)


def test_anomaly_vector_no_single_opaque_score():
    """El punto central del diseño: no existe ningún campo "score" único en
    AnomalyVector -- cada dimensión es independiente y verificable."""
    vector = AnomalyVector.create(detection_id="DET-0001", photometric=_z(4.2), morphological=_z(5.1))
    assert not hasattr(vector, "score")
    assert vector.flagged_dimensions == ("photometric", "morphological")
    assert vector.independent_evidence_count == 2
    assert vector.spectral is None


def test_anomaly_vector_rejects_unknown_dimension():
    with pytest.raises(ValueError):
        AnomalyVector.create(detection_id="DET-0001", made_up_dimension=_z(1.0))  # type: ignore[call-arg]


def test_anomaly_vector_not_available_excluded_from_flagged():
    vector = AnomalyVector.create(
        detection_id="DET-0001",
        physical=Quantity.not_available(unit="sigma", method="robust_z_score", reference="sin muestra de referencia"),
    )
    assert vector.flagged_dimensions == ()
    assert vector.independent_evidence_count == 0


def test_anomaly_vector_roundtrip():
    vector = AnomalyVector.create(detection_id="DET-0001", temporal=_z(6.0), spatial=_z(4.4))
    restored = AnomalyVector.from_dict(vector.to_dict())
    assert restored == vector
