"""Puente Fase 4 → Fase 6: convierte una fila de candidato tal como la
produce hoy `discovery_scan_observation()` (código heredado, sección "v57:
DISCOVERY WORKSPACE") al `Candidate` versionado nuevo.

Este módulo demuestra que el esquema diseñado en la Fase 4 es
efectivamente compatible con datos reales que el pipeline heredado ya
produce -- no es un diagrama de servilleta. También es, en sí mismo, la
primera pieza concreta de la Fase 7 (unificación de los tres pipelines de
descubrimiento, ver docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 6):
aquí es donde se resuelve, de forma explícita y auditable, la
correspondencia entre el vocabulario `discovery_state`/`catalog_state`
del Discovery Workspace y el vocabulario único `IdentificationState`
definido en la Fase 4 -- una correspondencia que antes no existía en
ningún sitio del código.

Deliberadamente NO se traduce la fila del pipeline OIII/Hα
(`analyze_pair_core`) todavía: ese pipeline tiene un contrato de
candidato distinto (física de choque, grids MAPPINGS) y su propio
adaptador es trabajo de la Fase 6/7, cuando se diseñe junto con el resto
de la unificación de motores -- traducirlo aquí de forma apresurada
arriesgaría inventar un mapeo que luego haya que deshacer.
"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from astrophysics_suite.core.enums import ArtifactKind, IdentificationState, MorphologyClass, QualityLevel
from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import ArtifactCheck, Candidate, CatalogMatch, CatalogQuery, QualitySummary
from astrophysics_suite.models.detection import MorphologySummary, SkyPosition

DISCOVERY_WORKSPACE_ENGINE_NAME = "discovery_scan_observation"


class ArtifactRejectedRow(Exception):
    """La fila fue rechazada como artefacto por el pipeline heredado antes
    de llegar aquí; no debe convertirse en Candidate. El Artifact
    Rejection Engine, no este adaptador, es quien decide esto -- este
    adaptador solo respeta la decisión ya tomada."""

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)


def identification_state_from_discovery_workspace_row(row: dict[str, Any]) -> IdentificationState:
    """Traduce discovery_state/catalog_state/anomaly_state (vocabulario del
    Discovery Workspace heredado) al IdentificationState único de la Fase 4.

    Lanza ArtifactRejectedRow si la fila nunca debió convertirse en
    Candidate (evidence_state == "REJECTED_ARTIFACT").
    """
    if row.get("evidence_state") == "REJECTED_ARTIFACT":
        raise ArtifactRejectedRow(row.get("artifact_reason", "artefacto sin razón registrada"))

    discovery_state = row.get("discovery_state")
    catalog_state = row.get("catalog_state")
    anomaly_state = row.get("anomaly_state")

    if catalog_state == "KNOWN_GAIA":
        return IdentificationState.KNOWN_VARIANT if anomaly_state == "MORPHOLOGY_OUTLIER" else IdentificationState.KNOWN
    if catalog_state == "UNMATCHED_GAIA" or discovery_state == "UNMATCHED":
        return IdentificationState.ANOMALOUS if anomaly_state == "MORPHOLOGY_OUTLIER" else IdentificationState.UNMATCHED
    if discovery_state in ("SCIENCE_CANDIDATE", "REVIEW"):
        return IdentificationState.DISCOVERY_REVIEW
    # discovery_state == "QUALITY_LIMITED" u otro no contemplado: no hay
    # evidencia suficiente para ningún estado más específico que esto.
    return IdentificationState.DISCOVERY_REVIEW


def candidate_from_discovery_workspace_row(
    row: dict[str, Any],
    *,
    observation_id: str,
    pipeline_version: str,
    produced_at: datetime | None = None,
) -> Candidate:
    """Construye un Candidate a partir de una fila real de
    `discovery_scan_observation()["candidates"]`.

    Lanza ArtifactRejectedRow (no devuelve None) si la fila es un
    artefacto rechazado -- forzar al llamador a decidir explícitamente
    qué hacer con artefactos es preferible a un valor de retorno
    ambiguo que se pueda ignorar por descuido.
    """
    identification_state = identification_state_from_discovery_workspace_row(row)

    candidate_id = str(row.get("candidate_id") or row.get("det_id"))
    x = float(row["x"])
    y = float(row["y"])
    position = SkyPosition(x_px=x, y_px=y)  # el Discovery Workspace heredado no emite RA/Dec por fuente hoy

    area_px = float(row.get("area_px", 0.0))
    elongation = float(row.get("elongation", 1.0))
    compactness = float(row.get("compactness", 0.0))
    morphology = MorphologySummary(
        morphology_class=MorphologyClass.POINT_SOURCE if elongation <= 2.0 and compactness >= 0.5 else MorphologyClass.EXTENDED,
        area_px=area_px,
        elongation=elongation,
        compactness=compactness,
    )

    peak_snr = row.get("peak_snr")
    snr = (
        Quantity(value=float(peak_snr), error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="peak_over_rms")
        if peak_snr is not None
        else None
    )

    flux_adu = row.get("flux_adu")
    flux: dict[str, Quantity] = {}
    bands = tuple(row.get("bands", ()))
    if flux_adu is not None and bands:
        flux[bands[0]] = Quantity(value=float(flux_adu), error=None, unit="ADU", kind=ValueKind.OBSERVED, method="aperture_sum")

    catalog_matches: tuple[CatalogMatch, ...] = ()
    catalog_non_matches: tuple[CatalogQuery, ...] = ()
    gaia_match = row.get("gaia_match")
    if gaia_match:
        mag = gaia_match.get("g_mag")
        catalog_matches = (
            CatalogMatch(
                catalog="Gaia DR3",
                catalog_id=str(gaia_match.get("source_id", "")),
                separation_arcsec=float(row.get("gaia_separation_arcsec") or 0.0),
                magnitude=Quantity(value=float(mag), error=None, unit="mag", kind=ValueKind.OBSERVED, method="gaia_phot_g_mean_mag") if mag is not None else None,
            ),
        )
    elif row.get("catalog_state") in ("UNMATCHED_GAIA", None):
        catalog_non_matches = (CatalogQuery(catalog="Gaia DR3", radius_arcsec=3.0, reason="sin fuente Gaia dentro del radio de búsqueda"),)

    artifact_reason = row.get("artifact_reason")
    artifact_checks = (
        (ArtifactCheck(kind=ArtifactKind.OTHER, flagged=False, notes=str(artifact_reason)),)
        if artifact_reason
        else ()
    )

    quality = QualitySummary(overall_level=QualityLevel.PASS if row.get("discovery_state") != "QUALITY_LIMITED" else QualityLevel.WARNING)

    provenance = Provenance.now(
        pipeline_version=pipeline_version,
        engine=DISCOVERY_WORKSPACE_ENGINE_NAME,
        engine_version="1.0",
    )
    if produced_at is not None:
        from dataclasses import replace

        provenance = replace(provenance, produced_at=produced_at)

    return Candidate.create(
        candidate_id=candidate_id,
        observation_id=observation_id,
        detection_id=str(row.get("det_id", candidate_id)),
        position=position,
        morphology=morphology,
        flux=flux,
        snr=snr,
        bands=bands,
        catalog_matches=catalog_matches,
        catalog_non_matches=catalog_non_matches,
        artifact_checks=artifact_checks,
        quality=quality,
        provenance=provenance,
        identification_state=identification_state,
    )
