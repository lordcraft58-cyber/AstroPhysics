"""Construcción de la `EvidenceChain` a partir de las evidencias tipadas
que producen los motores -- el ÚLTIMO paso científico antes del
`Candidate`.

## Independencia, no suma

La regla que se conserva del diseño original: la fuerza de un candidato
no es un número agregado, es **cuántos motores DISTINTOS e
independientes coinciden**. Por eso cada `EvidenceItem` lleva su
`source_engine`, y el recuento de independencia cuenta motores únicos,
no piezas. Dos señales del mismo motor no son dos evidencias.

El `priority_index` existe solo para ORDENAR la cola de revisión humana.
Nunca es una probabilidad, nunca decide nada por sí solo, y siempre se
puede desmontar en los `items` que lo componen.

Nada aquí declara un descubrimiento. Lo máximo que puede concluir esta
cadena es que hay evidencia independiente suficiente para que una
persona lo mire (`DISCOVERY_REVIEW`).
"""
from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.models.candidate import ArtifactCheck, CatalogMatch, CatalogQuery
from astrophysics_suite.models.evidence import DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE, EvidenceChain, EvidenceItem
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence
from astrophysics_suite.physics.constraints import ConsistencyResult

ENGINE_NAME = "evidence.chain_builder"
ENGINE_VERSION = "1.0"

#: Por debajo de esta significancia, una dimensión de anomalía no se
#: cuenta como evidencia: es ruido estadístico normal, no una señal.
DEFAULT_ANOMALY_SIGMA = 4.0

_ANOMALY_CATEGORIES = {
    "photometric": ("photometric_anomaly", "AnomalyEngine.photometric"),
    "morphological": ("morphological_anomaly", "AnomalyEngine.morphological"),
    "spectral": ("spectral_anomaly", "AnomalyEngine.spectral"),
    "temporal": ("temporal_evidence", "AnomalyEngine.temporal"),
    "astrometric": ("astrometric_anomaly", "AnomalyEngine.astrometric"),
    "spatial": ("spatial_anomaly", "AnomalyEngine.spatial"),
    "physical": ("physical_tension", "AnomalyEngine.physical"),
}


def build_evidence_chain(
    *,
    detection_id: str,
    anomaly: AnomalyVector | None = None,
    consistency: ConsistencyResult | None = None,
    temporal: TemporalEvidence | None = None,
    motion: MotionEvidence | None = None,
    catalog_matches: tuple[CatalogMatch, ...] = (),
    catalog_non_matches: tuple[CatalogQuery, ...] = (),
    artifact_checks: tuple[ArtifactCheck, ...] = (),
    anomaly_sigma_threshold: float = DEFAULT_ANOMALY_SIGMA,
    minimum_independent_evidence: int = DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE,
) -> EvidenceChain:
    """Reúne en una cadena auditable todo lo que los motores han
    producido realmente para esta fuente."""
    items: list[EvidenceItem] = []

    # --- Identificación: tanto la coincidencia como su ausencia informan ---
    for match in catalog_matches:
        items.append(EvidenceItem(
            category="catalog_match",
            description=f"Coincide con {match.catalog} {match.catalog_id} a {match.separation_arcsec:.2f}\".",
            source_engine="IdentificationEngine",
            supports_candidate=False,
            value=Quantity(
                value=float(match.separation_arcsec), error=None, unit="arcsec",
                kind=ValueKind.OBSERVED, method="catalog_crossmatch", reference=match.catalog,
            ),
        ))
    for query in catalog_non_matches:
        items.append(EvidenceItem(
            category="catalog_non_match",
            description=f"{query.catalog}: {query.reason} (radio {query.radius_arcsec:.1f}\").",
            source_engine="IdentificationEngine",
            supports_candidate="no disponible" not in query.reason.lower(),
        ))

    # --- Anomalías: solo las dimensiones realmente significativas ---
    if anomaly is not None:
        for dimension, (category, engine) in _ANOMALY_CATEGORIES.items():
            quantity = getattr(anomaly, dimension, None)
            if quantity is None or not quantity.is_available or quantity.value is None:
                continue
            if float(quantity.value) < anomaly_sigma_threshold:
                continue
            items.append(EvidenceItem(
                category=category,
                description=f"Anomalía {dimension}: {quantity.value:.2f} {quantity.unit} ({quantity.method}).",
                source_engine=engine,
                supports_candidate=True,
                value=quantity,
            ))

    # --- Física: tensiones internas concretas, con sus supuestos ---
    if consistency is not None:
        for issue in consistency.physical_tensions:
            assumptions = ", ".join(issue.assumptions) or "no declarados"
            items.append(EvidenceItem(
                category="physical_tension",
                description=(
                    f"{issue.constraint}: z={issue.z_score:.2f} bajo los supuestos {assumptions}."
                    if issue.z_score is not None
                    else f"{issue.constraint}: inconsistencia detectada bajo los supuestos {assumptions}."
                ),
                source_engine="PhysicalConstraintEngine",
                supports_candidate=True,
                value=(
                    Quantity(
                        value=abs(float(issue.z_score)), error=None, unit="sigma",
                        kind=ValueKind.OBSERVED, method="physical_constraint",
                        notes=issue.assumptions,
                    )
                    if issue.z_score is not None else None
                ),
            ))

    # --- Temporal y movimiento: solo si el motor concluyó algo real ---
    if temporal is not None and temporal.variable_candidate:
        items.append(EvidenceItem(
            category="temporal_evidence",
            description=f"Variabilidad detectada sobre {temporal.n_epochs} épocas.",
            source_engine="TemporalEngine",
            supports_candidate=True,
            value=temporal.brightness_change,
        ))
    if motion is not None and motion.moving_source_candidate:
        items.append(EvidenceItem(
            category="motion_evidence",
            description=f"Movimiento propio significativo sobre {motion.n_epochs_used} épocas.",
            source_engine="MotionEngine",
            supports_candidate=True,
            value=motion.pm_total,
        ))

    # --- Artefactos: evidencia EN CONTRA, nunca se oculta ---
    for check in artifact_checks:
        if check.flagged:
            items.append(EvidenceItem(
                category="artifact_check",
                description=f"Marcado como {check.kind.value}: {check.notes}",
                source_engine="ArtifactRejectionEngine",
                supports_candidate=False,
                value=check.confidence,
            ))

    priority_index = _priority_index(items, minimum_independent_evidence)
    return EvidenceChain.create(
        detection_id=detection_id,
        items=tuple(items),
        priority_index=priority_index,
        minimum_independent_evidence=minimum_independent_evidence,
    )


def _priority_index(items: list[EvidenceItem], minimum_independent_evidence: int) -> float:
    """Índice SOLO para ordenar la cola de revisión: número de motores
    independientes que apoyan el candidato, penalizado por la evidencia
    en contra. Nunca es una probabilidad ni un veredicto."""
    supporting_engines = {item.source_engine for item in items if item.supports_candidate}
    opposing = sum(1 for item in items if not item.supports_candidate and item.category == "artifact_check")
    return float(max(0, len(supporting_engines) - opposing))
