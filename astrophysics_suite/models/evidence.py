"""`EvidenceChain`: el núcleo conceptual del producto (ver el encargo
original). Una lista estructurada y auditable de piezas de evidencia --
nunca un único "Discovery Score" opaco.

Reimplementa, de forma más general, el principio ya presente y correcto
en `DiscoveryEvidenceEngine` del código heredado (ver
docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 13.2): independencia de
evidencias con un mínimo exigido, prioridad explicable y desmontable,
revisión humana siempre obligatoria.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrophysics_suite.core.quantity import Quantity

SCHEMA_VERSION = 1

DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE = 2


@dataclass(frozen=True)
class EvidenceItem:
    category: str
    """P. ej. "catalog_match", "catalog_non_match", "temporal_change",
    "motion", "morphology_anomaly", "physical_tension", "model_discrepancy",
    "visual_novelty", "artifact_check", "wcs_quality"."""
    description: str
    """Explicación legible por humanos de por qué esta pieza cuenta como
    evidencia -- es lo que se le muestra al revisor, no un código interno."""
    source_engine: str
    """Qué motor produjo esta pieza (p. ej. "IdentificationEngine",
    "TemporalEngine", "AnomalyEngine", "PhysicalEngine", "DiscoveryAI",
    "ArtifactRejectionEngine"). La independencia de evidencias se cuenta
    por motores DISTINTOS que coinciden, no por número de piezas."""
    supports_candidate: bool
    """True si esta pieza empuja hacia "candidato relevante"; False si es
    contexto neutro o evidencia en contra (p. ej. "artefacto probable")."""
    value: Quantity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "category": self.category,
            "description": self.description,
            "source_engine": self.source_engine,
            "supports_candidate": self.supports_candidate,
            "value": self.value.to_dict() if self.value else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceItem":
        return cls(
            category=data["category"],
            description=data["description"],
            source_engine=data["source_engine"],
            supports_candidate=bool(data["supports_candidate"]),
            value=Quantity.from_dict(data["value"]) if data.get("value") else None,
        )


@dataclass(frozen=True)
class EvidenceChain:
    schema_version: int
    detection_id: str
    items: tuple[EvidenceItem, ...]
    priority_index: float
    """Índice de prioridad compuesto -- SIEMPRE desmontable en `items`.
    Nunca se presenta ni se interpreta como una probabilidad."""
    minimum_independent_evidence: int = DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE
    human_verification_required: bool = True

    @classmethod
    def create(
        cls,
        *,
        detection_id: str,
        items: tuple[EvidenceItem, ...],
        priority_index: float,
        minimum_independent_evidence: int = DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE,
    ) -> "EvidenceChain":
        return cls(
            schema_version=SCHEMA_VERSION,
            detection_id=detection_id,
            items=items,
            priority_index=priority_index,
            minimum_independent_evidence=minimum_independent_evidence,
        )

    @property
    def supporting_engines(self) -> tuple[str, ...]:
        """Motores distintos que aportaron al menos una pieza a favor."""
        seen: list[str] = []
        for item in self.items:
            if item.supports_candidate and item.source_engine not in seen:
                seen.append(item.source_engine)
        return tuple(seen)

    @property
    def independent_evidence_count(self) -> int:
        return len(self.supporting_engines)

    @property
    def scientific_candidate_gate(self) -> bool:
        """Espejo directo de la política ya presente en el código heredado:
        una prioridad alta por sí sola no basta -- hacen falta motores
        independientes de acuerdo. Este contenedor nunca decide "es un
        descubrimiento"; solo si hay evidencia suficiente para pedir
        revisión humana."""
        return self.independent_evidence_count >= self.minimum_independent_evidence

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "items": [it.to_dict() for it in self.items],
            "priority_index": self.priority_index,
            "minimum_independent_evidence": self.minimum_independent_evidence,
            "human_verification_required": self.human_verification_required,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "EvidenceChain":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            items=tuple(EvidenceItem.from_dict(it) for it in data.get("items", ())),
            priority_index=data["priority_index"],
            minimum_independent_evidence=data.get("minimum_independent_evidence", DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE),
            human_verification_required=bool(data.get("human_verification_required", True)),
        )
