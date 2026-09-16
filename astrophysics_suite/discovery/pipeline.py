"""Modo genérico del Discovery Engine: `Observation -> list[Candidate]`,
agnóstico del tipo de objeto -- el equivalente tipado del antiguo
Discovery Workspace v57 (`discovery_scan_observation`), pero construido
sobre los motores reales extraídos en la Fase 6 en vez de reimplementar
su propia detección/identificación por separado (el defecto original
que la Fase 1 documentó: tres pipelines de descubrimiento paralelos que
no se hablaban entre sí -- ver docs/audit/01-..., seccion 6).

Orden de ejecución, siguiendo la filosofía central del encargo:
IMÁGENES -> DETECCIÓN -> RECHAZO DE ARTEFACTOS -> IDENTIFICACIÓN ->
CARACTERIZACIÓN -> CANDIDATO. El rechazo de artefactos ocurre ANTES de
que nada se considere candidato (una detección ARTIFACT_REJECTED nunca
llega a producir un Candidate) -- no después, como una anotación sobre
un candidato ya creado.
"""
from __future__ import annotations

from dataclasses import dataclass

from astrophysics_suite.artifacts.morphology_screen import classify_morphology
from astrophysics_suite.catalogs.gaia import identify_detection
from astrophysics_suite.core.enums import QualityLevel, ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.detection.point_sources import detect_point_sources
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.candidate import Candidate, QualityCheckItem, QualitySummary
from astrophysics_suite.models.observation import Observation
from astrophysics_suite.photometry.quality import characterize_point_source

_QUALITY_LEVEL_FOR_STATE = {
    "SCIENCE_CANDIDATE": QualityLevel.PASS,
    "REVIEW": QualityLevel.WARNING,
    "QUALITY_LIMITED": QualityLevel.WARNING,
}


@dataclass(frozen=True)
class DiscoveryRunSummary:
    """El resumen que el usuario final ve tras un escaneo -- ver el
    encargo original: "N fuentes detectadas, M identificadas, X no
    asociadas, Y anomalías y Z candidatos para revisión"."""

    observation_id: str
    n_images: int
    n_detected: int
    n_artifact_rejected: int
    n_candidates: int
    n_known: int
    n_unmatched: int
    n_discovery_review: int


def run_generic_discovery(
    observation: Observation,
    loaded_images: dict[str, LoadedImage],
    *,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 3000,
    match_radius_arcsec: float = 3.0,
    gaia_mag_limit: float = 20.0,
    pipeline_version: str = "",
) -> tuple[list[Candidate], DiscoveryRunSummary]:
    """Ejecuta el modo genérico sobre todas las imágenes de una
    `Observation` ya cargada (ver `io.fits_loader.build_observation`).

    `loaded_images` debe mapear `ImageRef.path` -> `LoadedImage`, tal como
    lo devuelve `build_observation`.
    """
    candidates: list[Candidate] = []
    n_detected = 0
    n_rejected = 0

    for image_ref in observation.images:
        loaded = loaded_images[image_ref.path]
        detections = detect_point_sources(
            loaded,
            observation_id=observation.observation_id,
            band=image_ref.band,
            fwhm_px=fwhm_px,
            threshold_sigma=threshold_sigma,
            max_sources=max_sources,
            pipeline_version=pipeline_version,
        )
        n_detected += len(detections)

        for detection in detections:
            state, reason = classify_morphology(detection)
            if state == "ARTIFACT_REJECTED":
                n_rejected += 1
                continue

            characterization = characterize_point_source(loaded, detection, pipeline_version=pipeline_version)
            identification_state, catalog_matches, catalog_non_matches = identify_detection(
                detection, match_radius_arcsec=match_radius_arcsec, mag_limit=gaia_mag_limit
            )

            quality = QualitySummary(
                overall_level=_QUALITY_LEVEL_FOR_STATE[state],
                checks=(QualityCheckItem(name="morphology_screen", level=_QUALITY_LEVEL_FOR_STATE[state], detail=reason),),
            )
            snr = Quantity(value=detection.peak_snr, error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method=detection.method)

            candidates.append(
                Candidate.create(
                    candidate_id=f"{observation.observation_id}-{detection.detection_id}",
                    observation_id=observation.observation_id,
                    detection_id=detection.detection_id,
                    position=characterization.position,
                    morphology=detection.morphology,
                    size=characterization.fwhm,
                    snr=snr,
                    bands=detection.bands,
                    catalog_matches=catalog_matches,
                    catalog_non_matches=catalog_non_matches,
                    provenance=detection.provenance,
                    identification_state=identification_state,
                    quality=quality,
                )
            )

    summary = DiscoveryRunSummary(
        observation_id=observation.observation_id,
        n_images=len(observation.images),
        n_detected=n_detected,
        n_artifact_rejected=n_rejected,
        n_candidates=len(candidates),
        n_known=sum(1 for c in candidates if c.identification_state.value == "KNOWN"),
        n_unmatched=sum(1 for c in candidates if c.identification_state.value == "UNMATCHED"),
        n_discovery_review=sum(1 for c in candidates if c.identification_state.value == "DISCOVERY_REVIEW"),
    )
    return candidates, summary
