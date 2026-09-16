from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.evidence import EvidenceChain, EvidenceItem


def _item(category: str, engine: str, supports: bool = True) -> EvidenceItem:
    return EvidenceItem(
        category=category,
        description=f"{category} evidence from {engine}",
        source_engine=engine,
        supports_candidate=supports,
        value=Quantity(value=5.0, error=0.5, unit="sigma", kind=ValueKind.OBSERVED, method="test"),
    )


def test_evidence_chain_independence_counts_distinct_engines_not_items():
    """Dos piezas del MISMO motor no deben contar como dos evidencias
    independientes -- ese es exactamente el error que produciría una caja
    negra que solo sumara puntos."""
    chain = EvidenceChain.create(
        detection_id="DET-0001",
        items=(
            _item("morphology_anomaly", "AnomalyEngine"),
            _item("physical_tension", "AnomalyEngine"),  # mismo motor
            _item("temporal_change", "TemporalEngine"),
        ),
        priority_index=0.7,
    )
    assert chain.independent_evidence_count == 2
    assert set(chain.supporting_engines) == {"AnomalyEngine", "TemporalEngine"}


def test_evidence_chain_gate_requires_minimum_independent_evidence():
    single_engine_chain = EvidenceChain.create(
        detection_id="DET-0001",
        items=(_item("morphology_anomaly", "AnomalyEngine"),),
        priority_index=0.9,
    )
    assert single_engine_chain.scientific_candidate_gate is False

    two_engine_chain = EvidenceChain.create(
        detection_id="DET-0001",
        items=(_item("morphology_anomaly", "AnomalyEngine"), _item("temporal_change", "TemporalEngine")),
        priority_index=0.9,
    )
    assert two_engine_chain.scientific_candidate_gate is True


def test_evidence_chain_non_supporting_items_dont_count():
    chain = EvidenceChain.create(
        detection_id="DET-0001",
        items=(
            _item("morphology_anomaly", "AnomalyEngine"),
            _item("artifact_check", "ArtifactRejectionEngine", supports=False),
        ),
        priority_index=0.4,
    )
    assert chain.independent_evidence_count == 1
    assert chain.scientific_candidate_gate is False


def test_evidence_chain_human_verification_always_required_by_default():
    chain = EvidenceChain.create(detection_id="DET-0001", items=(), priority_index=0.0)
    assert chain.human_verification_required is True


def test_evidence_chain_roundtrip():
    chain = EvidenceChain.create(
        detection_id="DET-0001",
        items=(_item("morphology_anomaly", "AnomalyEngine"), _item("temporal_change", "TemporalEngine")),
        priority_index=0.83,
    )
    restored = EvidenceChain.from_dict(chain.to_dict())
    assert restored == chain
    assert restored.scientific_candidate_gate == chain.scientific_candidate_gate
