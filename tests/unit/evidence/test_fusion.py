"""Nota importante descubierta al escribir estos tests (ver
docs/audit/08-FASE6-MOTORES-RESTANTES.md, seccion 7): las dos
comprobaciones de consistencia INTERNA de PhysicalConstraintEngine (edad
Sedov vs. radio/velocidad, y temperatura de choque fuerte vs. velocidad)
son inalcanzables en la práctica cuando se invocan a través de
DiscoveryEvidenceEngine.evaluate_rows() -- la ruta de producción real,
usada también por discovery_v46()/physical_discovery_bundle(). La razón:
esas comprobaciones leen radius_pc/velocity_kms desde `estimates` (la
salida de infer_physical_parameters), pero esa función nunca copia esos
observables crudos a su diccionario de salida -- solo sus magnitudes
derivadas (age_yr, postshock_temperature_K), que están garantizadas por
construcción a coincidir consigo mismas. Por eso estos tests verifican
las señales que SÍ son alcanzables por esa ruta (anomalía de referencia,
problema de medición) y no simulan una tensión física interna a través
de evaluate_rows -- hacerlo daría un falso positivo de "funciona" para
una ruta que en producción nunca se ejerce.
"""
from __future__ import annotations

from astrophysics_suite.evidence.fusion import evidence_chain_from_row


def test_no_row_produces_no_evidence_and_no_gate():
    chain = evidence_chain_from_row({}, detection_id="DET-0001")
    assert chain.items == ()
    assert chain.independent_evidence_count == 0
    assert chain.scientific_candidate_gate is False
    assert chain.human_verification_required is True


def test_single_reference_anomaly_is_not_enough_for_the_gate():
    row = {"velocity_kms": 100.0}
    reference = {"postshock_temperature_K": {"value": 100_000.0, "sigma": 5_000.0, "source": "literature"}}
    chain = evidence_chain_from_row(row, detection_id="DET-0002", reference=reference, sigma_threshold=4.0)
    assert chain.independent_evidence_count == 1
    assert chain.scientific_candidate_gate is False


def test_reference_anomaly_plus_visual_novelty_reaches_the_gate():
    row = {"velocity_kms": 100.0}
    reference = {"postshock_temperature_K": {"value": 100_000.0, "sigma": 5_000.0, "source": "literature"}}
    ai_result = {"novelty_state": "OUTLIER"}
    chain = evidence_chain_from_row(row, detection_id="DET-0003", reference=reference, ai_result=ai_result, sigma_threshold=4.0)
    assert chain.independent_evidence_count == 2
    assert {"ReferenceComparisonEngine", "DiscoveryAI"} <= set(item.source_engine for item in chain.items)
    assert chain.scientific_candidate_gate is True


def test_negative_ratio_is_a_measurement_issue_not_evidence():
    chain = evidence_chain_from_row({"ratio": -1.0}, detection_id="DET-0004")
    assert chain.items == ()
    assert chain.scientific_candidate_gate is False


def test_evidence_chain_roundtrip():
    from astrophysics_suite.models.evidence import EvidenceChain

    row = {"velocity_kms": 100.0}
    reference = {"postshock_temperature_K": {"value": 100_000.0, "sigma": 5_000.0, "source": "literature"}}
    chain = evidence_chain_from_row(row, detection_id="DET-0005", reference=reference)
    assert EvidenceChain.from_dict(chain.to_dict()) == chain
