from __future__ import annotations


import pytest

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity


def test_quantity_roundtrip():
    q = Quantity(value=12.5, error=0.3, unit="km/s", kind=ValueKind.MODEL_INFERENCE, method="rankine_hugoniot", reference="grid-v2")
    restored = Quantity.from_dict(q.to_dict())
    assert restored == q


def test_quantity_not_available_helper():
    q = Quantity.not_available(unit="km/s", method="rankine_hugoniot", reference="sin WCS")
    assert q.value is None
    assert q.is_available is False
    assert Quantity.from_dict(q.to_dict()) == q


def test_quantity_rejects_nan_with_non_not_available_kind():
    with pytest.raises(ValueError):
        Quantity(value=float("nan"), error=None, unit="km/s", kind=ValueKind.OBSERVED, method="direct")


def test_quantity_rejects_value_when_not_available():
    with pytest.raises(ValueError):
        Quantity(value=1.0, error=None, unit="km/s", kind=ValueKind.NOT_AVAILABLE, method="n/a")


def test_quantity_rejects_negative_error():
    with pytest.raises(ValueError):
        Quantity(value=1.0, error=-0.5, unit="km/s", kind=ValueKind.OBSERVED, method="direct")


def test_quantity_requires_method():
    with pytest.raises(ValueError):
        Quantity(value=1.0, error=None, unit="km/s", kind=ValueKind.OBSERVED, method="")


def test_quantity_is_frozen():
    q = Quantity(value=1.0, error=None, unit="km/s", kind=ValueKind.OBSERVED, method="direct")
    with pytest.raises(AttributeError):
        q.value = 2.0  # type: ignore[misc]


def test_provenance_roundtrip():
    p = Provenance.now(
        pipeline_version="0.4.0-dev",
        engine="DetectionEngine",
        engine_version="1.0",
        input_hashes=(("oiii_image", "abc123"),),
        warnings=("registro impreciso",),
    )
    restored = Provenance.from_dict(p.to_dict())
    assert restored == p
    assert restored.produced_at.tzinfo is not None
