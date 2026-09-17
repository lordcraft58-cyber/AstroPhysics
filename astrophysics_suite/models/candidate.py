"""`Candidate`: el centro del producto. No la imagen -- el candidato
científico y su evidencia (ver el encargo original, literal).

Estructura de datos versionada y serializable, con como mínimo los campos
que el encargo pide explícitamente: ID de candidato, ID de observación,
posición, RA/Dec, morfología, tamaño, flujo, S/N, bandas, catalog_matches,
catalog_non_matches, temporal_evidence, motion_evidence, physical_evidence,
anomaly_evidence, artefacto_checks, calidad, procedencia y estado.

`Candidate` es inmutable: una revisión humana no "sobreescribe" un
Candidate, produce uno nuevo (`mark_reviewed`) que conserva el historial
completo de revisiones en `review_notes`. Para un proyecto científico
pensado para conservarse durante años, perder el historial de por qué
alguien descartó o conservó un candidato es tan grave como perder el
candidato mismo.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Any

from astrophysics_suite.core.enums import ArtifactKind, IdentificationState, QualityLevel, ReviewState
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.models.detection import MorphologySummary, SkyPosition
from astrophysics_suite.models.evidence import EvidenceChain
from astrophysics_suite.models.physical import PhysicalInference
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class CatalogMatch:
    catalog: str
    """P. ej. "Gaia DR3", "SIMBAD"."""
    catalog_id: str
    separation_arcsec: float
    object_type: str = ""
    magnitude: Quantity | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "catalog": self.catalog,
            "catalog_id": self.catalog_id,
            "separation_arcsec": self.separation_arcsec,
            "object_type": self.object_type,
            "magnitude": self.magnitude.to_dict() if self.magnitude else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogMatch":
        return cls(
            catalog=data["catalog"],
            catalog_id=data["catalog_id"],
            separation_arcsec=data["separation_arcsec"],
            object_type=data.get("object_type", ""),
            magnitude=Quantity.from_dict(data["magnitude"]) if data.get("magnitude") else None,
        )


@dataclass(frozen=True)
class CatalogQuery:
    """Un catálogo consultado sin match -- la ausencia también es evidencia
    y debe quedar registrada con el mismo rigor que un match (nunca se
    interpreta, por sí sola, como novedad; ver docs/audit/02-...)."""

    catalog: str
    radius_arcsec: float
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"catalog": self.catalog, "radius_arcsec": self.radius_arcsec, "reason": self.reason}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CatalogQuery":
        return cls(catalog=data["catalog"], radius_arcsec=data["radius_arcsec"], reason=data.get("reason", ""))


@dataclass(frozen=True)
class ArtifactCheck:
    kind: ArtifactKind
    flagged: bool
    confidence: Quantity | None = None
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "kind": self.kind.value,
            "flagged": self.flagged,
            "confidence": self.confidence.to_dict() if self.confidence else None,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ArtifactCheck":
        return cls(
            kind=ArtifactKind(data["kind"]),
            flagged=bool(data["flagged"]),
            confidence=Quantity.from_dict(data["confidence"]) if data.get("confidence") else None,
            notes=data.get("notes", ""),
        )


@dataclass(frozen=True)
class QualityCheckItem:
    name: str
    level: QualityLevel
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"name": self.name, "level": self.level.value, "detail": self.detail}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualityCheckItem":
        return cls(name=data["name"], level=QualityLevel(data["level"]), detail=data.get("detail", ""))


@dataclass(frozen=True)
class QualitySummary:
    overall_level: QualityLevel
    checks: tuple[QualityCheckItem, ...] = ()

    def to_dict(self) -> dict[str, Any]:
        return {"overall_level": self.overall_level.value, "checks": [c.to_dict() for c in self.checks]}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "QualitySummary":
        return cls(
            overall_level=QualityLevel(data["overall_level"]),
            checks=tuple(QualityCheckItem.from_dict(c) for c in data.get("checks", ())),
        )


@dataclass(frozen=True)
class AIAssessment:
    """Evidencia adicional de un componente de IA -- nunca un veredicto.
    Declara explícitamente si el modelo se entrenó con datos reales o
    sintéticos (ver el encargo original: "el entrenamiento debe... distinguir
    claramente datos sintéticos de datos reales")."""

    model_name: str
    """P. ej. "AstroVision", "AstroDiscoveryAI", "TemporalAI"."""
    model_version: str
    trained_on: str
    """"real", "synthetic" o "real+synthetic" -- nunca implícito."""
    novelty_score: Quantity
    notes: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "model_name": self.model_name,
            "model_version": self.model_version,
            "trained_on": self.trained_on,
            "novelty_score": self.novelty_score.to_dict(),
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AIAssessment":
        return cls(
            model_name=data["model_name"],
            model_version=data["model_version"],
            trained_on=data["trained_on"],
            novelty_score=Quantity.from_dict(data["novelty_score"]),
            notes=data.get("notes", ""),
        )


@dataclass(frozen=True)
class ReviewNote:
    author: str
    created_at: datetime
    note: str
    previous_state: ReviewState | None
    new_state: ReviewState

    def to_dict(self) -> dict[str, Any]:
        return {
            "author": self.author,
            "created_at": self.created_at.isoformat(),
            "note": self.note,
            "previous_state": self.previous_state.value if self.previous_state else None,
            "new_state": self.new_state.value,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ReviewNote":
        return cls(
            author=data["author"],
            created_at=datetime.fromisoformat(data["created_at"]),
            note=data["note"],
            previous_state=ReviewState(data["previous_state"]) if data.get("previous_state") else None,
            new_state=ReviewState(data["new_state"]),
        )


@dataclass(frozen=True)
class Candidate:
    schema_version: int
    candidate_id: str
    observation_id: str
    detection_id: str
    position: SkyPosition
    morphology: MorphologySummary
    size: Quantity | None
    flux: dict[str, Quantity]
    snr: Quantity | None
    bands: tuple[str, ...]
    catalog_matches: tuple[CatalogMatch, ...]
    catalog_non_matches: tuple[CatalogQuery, ...]
    temporal_evidence: TemporalEvidence | None
    motion_evidence: MotionEvidence | None
    physical_evidence: PhysicalInference | None
    anomaly_evidence: AnomalyVector | None
    ai_evidence: tuple[AIAssessment, ...]
    artifact_checks: tuple[ArtifactCheck, ...]
    quality: QualitySummary
    provenance: Provenance
    identification_state: IdentificationState
    evidence_chain: EvidenceChain | None = None
    """La cadena de evidencia auditable que sustenta (o no) este
    candidato -- ver `evidence/chain_builder.py`. `None` cuando el
    pipeline que produjo este Candidate no la construyó (p. ej. rutas
    heredadas o de prueba anteriores a su introducción), nunca un
    marcador de "sin evidencia": esa distinción vive en
    `EvidenceChain.items`, que puede estar vacía legítimamente."""
    review_state: ReviewState = ReviewState.PENDING
    review_notes: tuple[ReviewNote, ...] = ()

    @classmethod
    def create(
        cls,
        *,
        candidate_id: str,
        observation_id: str,
        detection_id: str,
        position: SkyPosition,
        morphology: MorphologySummary,
        provenance: Provenance,
        identification_state: IdentificationState,
        quality: QualitySummary,
        size: Quantity | None = None,
        flux: dict[str, Quantity] | None = None,
        snr: Quantity | None = None,
        bands: tuple[str, ...] = (),
        catalog_matches: tuple[CatalogMatch, ...] = (),
        catalog_non_matches: tuple[CatalogQuery, ...] = (),
        temporal_evidence: TemporalEvidence | None = None,
        motion_evidence: MotionEvidence | None = None,
        physical_evidence: PhysicalInference | None = None,
        anomaly_evidence: AnomalyVector | None = None,
        ai_evidence: tuple[AIAssessment, ...] = (),
        artifact_checks: tuple[ArtifactCheck, ...] = (),
        evidence_chain: EvidenceChain | None = None,
    ) -> "Candidate":
        return cls(
            schema_version=SCHEMA_VERSION,
            candidate_id=candidate_id,
            observation_id=observation_id,
            detection_id=detection_id,
            position=position,
            morphology=morphology,
            size=size,
            flux=dict(flux or {}),
            snr=snr,
            bands=bands,
            catalog_matches=catalog_matches,
            catalog_non_matches=catalog_non_matches,
            temporal_evidence=temporal_evidence,
            motion_evidence=motion_evidence,
            physical_evidence=physical_evidence,
            anomaly_evidence=anomaly_evidence,
            ai_evidence=ai_evidence,
            artifact_checks=artifact_checks,
            quality=quality,
            provenance=provenance,
            identification_state=identification_state,
            evidence_chain=evidence_chain,
            review_state=ReviewState.PENDING,
            review_notes=(),
        )

    def mark_reviewed(self, *, new_state: ReviewState, author: str, note: str, reviewed_at: datetime) -> "Candidate":
        """Devuelve un Candidate nuevo con el estado de revisión actualizado
        y la nota añadida al historial -- nunca muta ni descarta el
        historial anterior. La aplicación NUNCA llama a esto para declarar
        un descubrimiento oficial; solo para que un humano conserve,
        descarte o marque para revisión."""
        if new_state == ReviewState.PENDING:
            raise ValueError("mark_reviewed no puede volver a PENDING -- ese es solo el estado inicial")
        review_note = ReviewNote(
            author=author,
            created_at=reviewed_at,
            note=note,
            previous_state=self.review_state,
            new_state=new_state,
        )
        return replace(self, review_state=new_state, review_notes=self.review_notes + (review_note,))

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "candidate_id": self.candidate_id,
            "observation_id": self.observation_id,
            "detection_id": self.detection_id,
            "position": self.position.to_dict(),
            "morphology": self.morphology.to_dict(),
            "size": self.size.to_dict() if self.size else None,
            "flux": {k: v.to_dict() for k, v in self.flux.items()},
            "snr": self.snr.to_dict() if self.snr else None,
            "bands": list(self.bands),
            "catalog_matches": [m.to_dict() for m in self.catalog_matches],
            "catalog_non_matches": [m.to_dict() for m in self.catalog_non_matches],
            "temporal_evidence": self.temporal_evidence.to_dict() if self.temporal_evidence else None,
            "motion_evidence": self.motion_evidence.to_dict() if self.motion_evidence else None,
            "physical_evidence": self.physical_evidence.to_dict() if self.physical_evidence else None,
            "anomaly_evidence": self.anomaly_evidence.to_dict() if self.anomaly_evidence else None,
            "ai_evidence": [a.to_dict() for a in self.ai_evidence],
            "artifact_checks": [a.to_dict() for a in self.artifact_checks],
            "quality": self.quality.to_dict(),
            "provenance": self.provenance.to_dict(),
            "identification_state": self.identification_state.value,
            "evidence_chain": self.evidence_chain.to_dict() if self.evidence_chain else None,
            "review_state": self.review_state.value,
            "review_notes": [n.to_dict() for n in self.review_notes],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Candidate":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            candidate_id=data["candidate_id"],
            observation_id=data["observation_id"],
            detection_id=data["detection_id"],
            position=SkyPosition.from_dict(data["position"]),
            morphology=MorphologySummary.from_dict(data["morphology"]),
            size=Quantity.from_dict(data["size"]) if data.get("size") else None,
            flux={k: Quantity.from_dict(v) for k, v in data.get("flux", {}).items()},
            snr=Quantity.from_dict(data["snr"]) if data.get("snr") else None,
            bands=tuple(data.get("bands", ())),
            catalog_matches=tuple(CatalogMatch.from_dict(m) for m in data.get("catalog_matches", ())),
            catalog_non_matches=tuple(CatalogQuery.from_dict(m) for m in data.get("catalog_non_matches", ())),
            temporal_evidence=TemporalEvidence.from_dict(data["temporal_evidence"]) if data.get("temporal_evidence") else None,
            motion_evidence=MotionEvidence.from_dict(data["motion_evidence"]) if data.get("motion_evidence") else None,
            physical_evidence=PhysicalInference.from_dict(data["physical_evidence"]) if data.get("physical_evidence") else None,
            anomaly_evidence=AnomalyVector.from_dict(data["anomaly_evidence"]) if data.get("anomaly_evidence") else None,
            ai_evidence=tuple(AIAssessment.from_dict(a) for a in data.get("ai_evidence", ())),
            artifact_checks=tuple(ArtifactCheck.from_dict(a) for a in data.get("artifact_checks", ())),
            quality=QualitySummary.from_dict(data["quality"]),
            provenance=Provenance.from_dict(data["provenance"]),
            identification_state=IdentificationState(data["identification_state"]),
            evidence_chain=EvidenceChain.from_dict(data["evidence_chain"]) if data.get("evidence_chain") else None,
            review_state=ReviewState(data.get("review_state", ReviewState.PENDING.value)),
            review_notes=tuple(ReviewNote.from_dict(n) for n in data.get("review_notes", ())),
        )

