"""Contratos de datos versionados del Discovery Engine.

Ver docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md, seccion 2, para el
diseño de cada motor, y docs/audit/05-FASE4-CONTRATOS-DE-DATOS.md para el
razonamiento detrás de estas clases concretas.
"""
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.models.candidate import (
    AIAssessment,
    ArtifactCheck,
    Candidate,
    CatalogMatch,
    CatalogQuery,
    QualityCheckItem,
    QualitySummary,
    ReviewNote,
)
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition
from astrophysics_suite.models.evidence import EvidenceChain, EvidenceItem
from astrophysics_suite.models.observation import ImageRef, Observation
from astrophysics_suite.models.physical import PhysicalInference
from astrophysics_suite.models.project import Project
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence

__all__ = [
    "AIAssessment",
    "AnomalyVector",
    "ArtifactCheck",
    "Candidate",
    "CatalogMatch",
    "CatalogQuery",
    "CharacterizationResult",
    "Detection",
    "EvidenceChain",
    "EvidenceItem",
    "ImageRef",
    "MorphologySummary",
    "MotionEvidence",
    "Observation",
    "PhysicalInference",
    "Project",
    "QualityCheckItem",
    "QualitySummary",
    "ReviewNote",
    "SkyPosition",
    "TemporalEvidence",
]
