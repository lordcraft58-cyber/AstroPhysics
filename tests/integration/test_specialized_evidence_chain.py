"""Prueba de integración del "modo especializado" (choque OIII/Hα):
physics.inference + anomaly.physical_tension + evidence.fusion
trabajando juntos sobre una misma fila de observables, ensamblados en un
Candidate completo -- con physical_evidence y anomaly_evidence poblados,
algo que el modo genérico (test_generic_discovery_pipeline.py) nunca
produce porque no tiene observables físicos.

No parte de píxeles reales: la extracción de la parte de
`analyze_pair_core` que mide estos observables desde la imagen (perfiles,
ratios de línea) queda para una fase posterior (ver
docs/audit/09-FASE7-DISCOVERY-ENGINE.md). Esta prueba demuestra que, una
vez que existan esos observables, los tres motores ya extraídos
componen correctamente sin más pegamento que el aquí escrito.
"""
from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.anomaly.physical_tension import physical_anomaly_quantity
from astrophysics_suite.core.enums import IdentificationState, QualityLevel, ReviewState
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.evidence.fusion import evidence_chain_from_row
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.models.candidate import Candidate, QualitySummary
from astrophysics_suite.models.detection import MorphologyClass, MorphologySummary, SkyPosition
from astrophysics_suite.physics.inference import infer_physical_inference


def test_specialized_pipeline_composes_physics_anomaly_and_evidence():
    row = {
        "ratio": 3.2,
        "ratio_err": 0.15,
        "velocity_kms": 180.0,
        "velocity_err_kms": 12.0,
        "offset_arcsec": 8.0,
        "offset_err_arcsec": 0.6,
    }
    # Para velocity_kms=180 la temperatura post-choque inferida es ~449 000 K
    # (rankine_hugoniot, gamma=5/3); se compara contra una referencia
    # deliberadamente alejada para que la tensión sea inequívoca (~6.6 sigma).
    reference = {"postshock_temperature_K": {"value": 50_000.0, "sigma": 10_000.0, "source": "literature_shock_fronts"}}
    ai_result = {"novelty_state": "OUTLIER"}

    physical_inference = infer_physical_inference(row, detection_id="DET-SPEC-0001", object_family="shock_front", distance_pc=1500.0)
    assert physical_inference.domain_valid
    assert "postshock_temperature_K" in physical_inference.parameters

    physical_quantity = physical_anomaly_quantity(row, physical_inference.parameters, reference=reference, min_sigma=4.0)
    anomaly_vector = AnomalyVector.create(detection_id="DET-SPEC-0001", physical=physical_quantity)
    assert anomaly_vector.physical is not None
    assert anomaly_vector.physical.is_available

    evidence_chain = evidence_chain_from_row(row, detection_id="DET-SPEC-0001", reference=reference, ai_result=ai_result, sigma_threshold=4.0)
    # Dos motores independientes coinciden (comparación de referencia + novedad visual) -> gate real.
    assert evidence_chain.independent_evidence_count >= 2
    assert evidence_chain.scientific_candidate_gate is True

    candidate = Candidate.create(
        candidate_id="CAND-SPEC-0001",
        observation_id="OBS-SPEC-0001",
        detection_id="DET-SPEC-0001",
        position=SkyPosition(x_px=200.0, y_px=150.0),
        morphology=MorphologySummary(morphology_class=MorphologyClass.FILAMENT, area_px=340.0, elongation=3.5, compactness=0.2),
        physical_evidence=physical_inference,
        anomaly_evidence=anomaly_vector,
        quality=QualitySummary(overall_level=QualityLevel.PASS),
        provenance=Provenance.now(pipeline_version="test", engine="discovery.specialized", engine_version="1.0"),
        identification_state=IdentificationState.DISCOVERY_REVIEW,
    )

    # El candidato ensamblado transporta la cadena completa de evidencia
    # física y de anomalía -- nunca colapsa todo a un único número.
    assert candidate.physical_evidence is physical_inference
    assert candidate.anomaly_evidence is anomaly_vector
    assert candidate.identification_state is IdentificationState.DISCOVERY_REVIEW  # nunca "descubierto", ni con gate=True

    restored = Candidate.from_dict(candidate.to_dict())
    assert restored == candidate

    reviewed = candidate.mark_reviewed(
        new_state=ReviewState.FLAGGED,
        author="revisor.humano",
        note="Evidencia convergente (referencia + IA visual); requiere seguimiento espectroscópico.",
        reviewed_at=datetime.now(timezone.utc),
    )
    assert reviewed.review_notes[-1].note.startswith("Evidencia convergente")
