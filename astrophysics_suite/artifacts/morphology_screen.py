"""Filtro morfológico de artefactos -> `ArtifactCheck` / `QualityCheckItem`.

Separa deliberadamente dos preguntas que el clasificador heredado
(`legacy...AstroPhysicsSuite_v57_3_COMMERCIAL._label_discovery_morphology`,
ahora migrado nativamente aquí -- ver "Migración" más abajo) respondía
juntas en un único (state, reason): "¿es esto probablemente un artefacto
instrumental/de procesado?" (una cuestión de `ArtifactCheck`) y "¿qué tan
limitada es la calidad de esta medición?" (una cuestión de
`QualitySummary`). Conflarlas -- como hacía el estado heredado
`QUALITY_LIMITED`, que no es ni un artefacto confirmado ni una fuente
limpia -- es exactamente el tipo de vocabulario mezclado que la Fase 4
existe para resolver (ver docs/audit/01-..., seccion 8.1).

## Migración (cierre del motor de rechazo de artefactos, informe 87)

`_label_discovery_morphology` es una cadena corta de comparaciones de
umbral sobre escalares ya calculados (área, elongación, compactness,
S/N de pico) -- sin ningún cálculo geométrico/estadístico propio que
migrar con riesgo real (a diferencia de, p. ej., la fórmula de FWHM de
Detection, informe 54). `classify_morphology` reproduce la MISMA cadena
de umbrales, verificada 1:1 contra el original en
`tests/regression/test_morphology_screen_matches_legacy.py` antes de
quitar la delegación -- último import de `legacy` en la ruta de rechazo
de artefactos.
"""
from __future__ import annotations

import math

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
    """Clasificación descriptiva para separar fuentes científicas de
    artefactos a partir de medidas morfológicas ya calculadas -- no
    declara ningún objeto nuevo, solo documenta señales observables.
    Devuelve (state, reason): uno de SCIENCE_CANDIDATE, REVIEW,
    QUALITY_LIMITED, ARTIFACT_REJECTED. Misma cadena de umbrales que el
    clasificador heredado (ver "Migración" arriba), reproducida aquí de
    forma nativa."""
    area = detection.morphology.area_px
    elongation = detection.morphology.elongation
    compactness = detection.morphology.compactness
    peak_snr = detection.peak_snr
    if not all(math.isfinite(float(x)) for x in (area, elongation, compactness, peak_snr)):
        return "QUALITY_LIMITED", "medición incompleta"
    if elongation >= 8.0:
        return "ARTIFACT_REJECTED", "traza lineal/elongación extrema"
    if area <= 2.0:
        return "ARTIFACT_REJECTED", "fuente demasiado compacta para caracterización robusta"
    if peak_snr < 4.0:
        return "QUALITY_LIMITED", "S/N insuficiente"
    if elongation <= 2.5 and compactness >= 0.18:
        return "SCIENCE_CANDIDATE", "morfología compatible con fuente astronómica"
    return "REVIEW", "morfología no concluyente"


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
