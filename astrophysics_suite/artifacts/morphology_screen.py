"""Filtro morfológico de artefactos -> `ArtifactCheck` / `QualityCheckItem`.

Separa deliberadamente dos preguntas que `legacy...
_label_discovery_morphology()` respondía juntas en un único (state, reason):
"¿es esto probablemente un artefacto instrumental/de procesado?" (una
cuestión de `ArtifactCheck`) y "¿qué tan limitada es la calidad de esta
medición?" (una cuestión de `QualitySummary`). Conflarlas -- como hacía el
estado heredado `QUALITY_LIMITED`, que no es ni un artefacto confirmado ni
una fuente limpia -- es exactamente el tipo de vocabulario mezclado que la
Fase 4 existe para resolver (ver docs/audit/01-..., seccion 8.1).
"""
from __future__ import annotations

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import (
    _label_discovery_morphology as _legacy_label_discovery_morphology,
)

from astrophysics_suite.core.enums import ArtifactKind, QualityLevel
from astrophysics_suite.models.candidate import ArtifactCheck, QualityCheckItem
from astrophysics_suite.models.detection import Detection

_STATE_TO_QUALITY_LEVEL = {
    "SCIENCE_CANDIDATE": QualityLevel.PASS,
    "REVIEW": QualityLevel.WARNING,
    "QUALITY_LIMITED": QualityLevel.WARNING,
    "ARTIFACT_REJECTED": QualityLevel.FAIL,
}


def classify_morphology(detection: Detection) -> tuple[str, str]:
    """Delega en el clasificador heredado. Devuelve (state, reason) tal cual:
    uno de SCIENCE_CANDIDATE, REVIEW, QUALITY_LIMITED, ARTIFACT_REJECTED."""
    return _legacy_label_discovery_morphology(
        detection.morphology.area_px,
        detection.morphology.elongation,
        detection.morphology.compactness,
        detection.peak_snr,
    )


def artifact_checks_for(detection: Detection) -> tuple[ArtifactCheck, ...]:
    state, reason = classify_morphology(detection)
    if state != "ARTIFACT_REJECTED":
        return ()
    # Solo se distingue "traza/elongación extrema" (umbral explícito en el
    # código heredado) del resto; no hay base para afinar más sin lógica
    # nueva no validada.
    kind = ArtifactKind.PROCESSING_ARTIFACT if detection.morphology.elongation >= 8.0 else ArtifactKind.OTHER
    return (ArtifactCheck(kind=kind, flagged=True, notes=reason),)


def quality_check_for(detection: Detection) -> QualityCheckItem:
    state, reason = classify_morphology(detection)
    return QualityCheckItem(name="morphology_screen", level=_STATE_TO_QUALITY_LEVEL[state], detail=reason)
