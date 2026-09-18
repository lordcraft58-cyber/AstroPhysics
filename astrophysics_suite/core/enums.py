"""Vocabularios compartidos por todos los motores.

Estos enums existen para cerrar el hallazgo de la Fase 1 (auditoria,
seccion 8.1): el código heredado contiene al menos tres vocabularios de
estado distintos y no unificados ("OBSERVABLE"/"NO DISPONIBLE" en el
pipeline general; "SCIENCE_CANDIDATE"/"ARTIFACT_REJECTED"/... en el
Discovery Workspace v57; y el vocabulario que el propio encargo pide
para el producto final). A partir de la Fase 4, este es el ÚNICO
vocabulario válido -- cualquier motor nuevo o extraído debe emitir
estos valores, no strings libres.
"""
from __future__ import annotations

import enum


class ValueKind(str, enum.Enum):
    """Estatus epistémico de un valor numérico (Quantity.kind).

    Operacionaliza el principio central del Physical Engine (ver
    docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 13.1): "es
    fundamental distinguir una medición directa, un observable, un
    proxy, una inferencia de modelo y una hipótesis física". El código
    heredado ya seguía esta disciplina como convención de strings
    ("OBSERVABLE", "PROXY OBSERVACIONAL", "INFERENCIA DE MODELO"); aquí
    se convierte en un tipo que el resto del sistema puede verificar,
    no solo leer.
    """

    OBSERVED = "OBSERVED"
    """Medición directa a partir de los píxeles/la observación."""

    PROXY = "PROXY"
    """Derivado de un observable mediante una relación simple y declarada,
    sin un modelo físico validado detrás (p. ej. una razón de flujos)."""

    MODEL_INFERENCE = "MODEL_INFERENCE"
    """Requiere un modelo físico o grid validado (hash + procedencia); nunca
    un grid de demostración presentado como si fuera publicable."""

    HYPOTHESIS = "HYPOTHESIS"
    """Plausible pero no confirmado; no debe tratarse como una medición."""

    NOT_AVAILABLE = "NOT_AVAILABLE"
    """El dato no está disponible (falta WCS, falta calibración, etc.) y el
    sistema lo declara explícitamente en vez de inferir de más."""


class IdentificationState(str, enum.Enum):
    """Estado operativo/científico de una detección tras el Identification
    Engine. Son estados descriptivos, NUNCA una declaración automática de
    descubrimiento (ver docs/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md, seccion 2.3).
    """

    KNOWN = "KNOWN"
    KNOWN_VARIANT = "KNOWN_VARIANT"
    UNMATCHED = "UNMATCHED"
    ANOMALOUS = "ANOMALOUS"
    TRANSIENT_CANDIDATE = "TRANSIENT_CANDIDATE"
    MOVING_SOURCE_CANDIDATE = "MOVING_SOURCE_CANDIDATE"
    DISCOVERY_REVIEW = "DISCOVERY_REVIEW"


class ReviewState(str, enum.Enum):
    """Estado de la revisión humana de un Candidate."""

    PENDING = "PENDING"
    KEPT = "KEPT"
    REJECTED = "REJECTED"
    FLAGGED = "FLAGGED"


class ArtifactKind(str, enum.Enum):
    """Categorías que el Artifact Rejection Engine debe poder distinguir
    (ver el encargo original: ruido, hot pixels, rayos cósmicos, saturación,
    defectos de PSF, reflejos, gradientes, donuts, errores de registro,
    residuos de stacking/sustracción, estructuras de procesado, trazas de
    aviones/satélites)."""

    NOISE = "NOISE"
    HOT_PIXEL = "HOT_PIXEL"
    COSMIC_RAY = "COSMIC_RAY"
    SATURATION = "SATURATION"
    PSF_DEFECT = "PSF_DEFECT"
    REFLECTION = "REFLECTION"
    GRADIENT = "GRADIENT"
    DONUT = "DONUT"
    REGISTRATION_ERROR = "REGISTRATION_ERROR"
    STACKING_RESIDUAL = "STACKING_RESIDUAL"
    PROCESSING_ARTIFACT = "PROCESSING_ARTIFACT"
    SATELLITE_OR_AIRPLANE_TRAIL = "SATELLITE_OR_AIRPLANE_TRAIL"
    OTHER = "OTHER"


class QualityLevel(str, enum.Enum):
    """Nivel de un chequeo de calidad individual (QC, PSF, WCS, registro...)."""

    PASS = "PASS"
    WARNING = "WARNING"
    FAIL = "FAIL"
    NOT_AVAILABLE = "NOT_AVAILABLE"


class MorphologyClass(str, enum.Enum):
    """Taxonomía morfológica que el Detection Engine debe poder asignar
    (ver el encargo original: fuentes puntuales, extendidas, blobs,
    filamentos, arcos, conchas, estructuras compactas, elongaciones,
    dobles, halos, jets, condensaciones)."""

    POINT_SOURCE = "POINT_SOURCE"
    EXTENDED = "EXTENDED"
    BLOB = "BLOB"
    FILAMENT = "FILAMENT"
    ARC = "ARC"
    SHELL = "SHELL"
    COMPACT = "COMPACT"
    ELONGATED = "ELONGATED"
    DOUBLE = "DOUBLE"
    HALO = "HALO"
    JET = "JET"
    CONDENSATION = "CONDENSATION"
    UNCLASSIFIED = "UNCLASSIFIED"
