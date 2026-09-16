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

import threading
from dataclasses import dataclass
from typing import Callable

from astrophysics_suite.artifacts.morphology_screen import classify_morphology
from astrophysics_suite.astrometry.plate_solve import estimate_approx_pointing_from_header, solve_plate
from astrophysics_suite.astrometry.wcs_fit import wcs_solution_to_astropy
from astrophysics_suite.catalogs.gaia import identify_detection
from astrophysics_suite.catalogs.simbad import resolve_object_coordinates
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


class DiscoveryCancelled(Exception):
    """El usuario canceló la ejecución -- ver `cancel` en
    `run_generic_discovery`. Mismo patrón que `AnalysisCancelled` en el
    código heredado (`legacy...analyze_pair_core`)."""


# Estados reales y mutuamente excluyentes del WCS de cada imagen al
# entrar en Discovery -- nunca "sin WCS" a secas: el motivo concreto
# (ya lo traía / se resolvió automáticamente / se intentó y falló / no
# se intentó) debe llegar a la GUI para que el usuario sepa exactamente
# qué análisis pudieron ejecutarse con coordenadas celestes y cuáles no.
WCS_STATE_PRESENT = "WCS_PRESENTE"
WCS_STATE_AUTO_RESOLVED = "WCS_RESUELTO_Y_VALIDADO_AUTOMATICAMENTE"
WCS_STATE_SOLVE_FAILED = "PLATE_SOLVING_FALLIDO"
WCS_STATE_SOLVE_NOT_RUN = "PLATE_SOLVING_NO_EJECUTADO"


@dataclass(frozen=True)
class ImageWCSStatus:
    """Resultado real de intentar asegurar un WCS para una imagen antes
    de detectar/identificar fuentes -- consumido por la GUI para mostrar
    con claridad qué pasó con cada imagen (nunca solo "Error")."""

    path: str
    band: str
    state: str
    """Uno de `WCS_STATE_*` -- nunca un texto genérico inventado aquí."""
    detail: str
    """Mensaje legible: por qué ya tenía WCS, qué encontró el plate
    solving (proveedor, RMS, nº de estrellas) o por qué falló/no se
    intentó."""


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
    wcs_status: tuple[ImageWCSStatus, ...] = ()


def _resolve_approx_pointing(header: dict, target_name: str) -> tuple[float, float, str] | None:
    """Puntero aproximado para `solve_plate`: primero el header FITS (si
    trae RA/DEC u OBJCTRA/OBJCTDEC reconocibles); si no, SIMBAD por el
    NOMBRE del objetivo de la observación (el mismo que el usuario
    escribió en "Nueva observación") -- igual que "Spectrophotometric
    Color Calibration" de PixInsight: el usuario da el nombre real, no
    depende de que la cámara/montura haya escrito RA/Dec en el header
    (con software de captura real, a menudo falta o está en una clave
    distinta). Nunca inventa un puntero -- `None` si ninguna de las dos
    fuentes resuelve."""
    pointing = estimate_approx_pointing_from_header(header)
    if pointing is not None:
        return pointing[0], pointing[1], "header FITS"
    resolved = resolve_object_coordinates(target_name)
    if resolved is not None:
        ra, dec, source = resolved
        return ra, dec, source
    return None


def _ensure_wcs(
    loaded: LoadedImage, image_ref, *, target_name: str, auto_plate_solve: bool,
    report: Callable[[float, str], None], progress_fraction: float,
) -> ImageWCSStatus:
    """Se asegura de que `loaded.legacy_image.wcs` esté disponible antes
    de detectar fuentes, intentando plate solving automático si falta --
    nunca inventa un WCS ni convierte su ausencia en una excepción:
    cuando no se puede, lo registra explícitamente y Discovery continúa
    (el resto de motores ya degradan con gracia sin WCS, ver
    `catalogs/gaia.py`)."""
    fits_image = loaded.legacy_image
    if fits_image.wcs is not None:
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_PRESENT,
            detail="El FITS ya traía un WCS válido en la cabecera -- no hizo falta resolver la placa.",
        )
    if not auto_plate_solve:
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_SOLVE_NOT_RUN,
            detail="Resolución automática de placa desactivada para este análisis -- WCS no disponible, "
                   "continuando sin coordenadas celestes para esta imagen.",
        )
    approx = _resolve_approx_pointing(fits_image.header or {}, target_name)
    approx_ra = approx[0] if approx is not None else None
    approx_dec = approx[1] if approx is not None else None
    pointing_note = f" (puntero: {approx[2]})" if approx is not None else ""
    report(progress_fraction, f"Resolviendo WCS automáticamente para {image_ref.band}{pointing_note}...")
    result = solve_plate(fits_image.data, fits_image.header or {}, approx_ra_deg=approx_ra, approx_dec_deg=approx_dec)
    if not result.success:
        pointing_hint = (
            " Ninguna posición aproximada disponible (ni en el header FITS ni resolviendo por SIMBAD el nombre "
            "del objetivo) -- comprueba que el nombre de la observación sea un objeto real reconocible."
            if approx is None else ""
        )
        return ImageWCSStatus(
            path=image_ref.path, band=image_ref.band, state=WCS_STATE_SOLVE_FAILED,
            detail=f"Plate solving falló: {result.reason}{pointing_hint} -- WCS no disponible, continuando sin "
                   f"coordenadas celestes para esta imagen (usa Astrometría -> Resolver placa automáticamente... "
                   f"o Ajustar WCS manualmente... para intentarlo con otros parámetros).",
        )
    fits_image.wcs = wcs_solution_to_astropy(result.solution)
    return ImageWCSStatus(
        path=image_ref.path, band=image_ref.band, state=WCS_STATE_AUTO_RESOLVED,
        detail=f"WCS resuelto y validado automáticamente ({result.provider}), puntero{pointing_note}: {result.reason}.",
    )


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
    progress: Callable[[float, str], None] | None = None,
    cancel: threading.Event | None = None,
    auto_plate_solve: bool = True,
) -> tuple[list[Candidate], DiscoveryRunSummary]:
    """Ejecuta el modo genérico sobre todas las imágenes de una
    `Observation` ya cargada (ver `io.fits_loader.build_observation`).

    `loaded_images` debe mapear `ImageRef.path` -> `LoadedImage`, tal como
    lo devuelve `build_observation`.

    `progress(fraccion_0_a_1, mensaje)` y `cancel` (un `threading.Event`)
    siguen la misma convención que `legacy...analyze_pair_core` -- pensado
    para ejecutarse en un hilo de fondo desde una GUI, nunca en el hilo
    principal (ver docs/audit/10-FASE8-GUI.md).

    Antes de detectar fuentes en cada imagen, si le falta WCS y
    `auto_plate_solve` está activo (por defecto), se intenta resolución
    automática (`astrometry.plate_solve.solve_plate`) -- la ausencia de
    WCS nunca aborta el análisis: si no se puede resolver, se registra
    el motivo exacto en `DiscoveryRunSummary.wcs_status` y esa imagen
    sigue por el resto del pipeline sin coordenadas celestes (las
    identificaciones que las necesiten degradan con gracia, ver
    `catalogs/gaia.py`)."""

    def report(fraction: float, message: str) -> None:
        if progress is not None:
            progress(fraction, message)

    def check_cancelled() -> None:
        if cancel is not None and cancel.is_set():
            raise DiscoveryCancelled("Análisis cancelado por el usuario")

    candidates: list[Candidate] = []
    n_detected = 0
    n_rejected = 0
    n_images = max(1, len(observation.images))
    wcs_statuses: list[ImageWCSStatus] = []

    for image_index, image_ref in enumerate(observation.images):
        check_cancelled()
        loaded = loaded_images[image_ref.path]
        wcs_statuses.append(
            _ensure_wcs(
                loaded, image_ref, target_name=observation.target_name, auto_plate_solve=auto_plate_solve,
                report=report, progress_fraction=image_index / n_images,
            )
        )
        check_cancelled()
        report(image_index / n_images, f"Detectando fuentes en {image_ref.band} ({image_index + 1}/{n_images})")
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

        for detection_index, detection in enumerate(detections):
            check_cancelled()
            if detections:
                within_image = detection_index / len(detections)
                report((image_index + within_image) / n_images, f"Caracterizando fuente {detection_index + 1}/{len(detections)}")

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

    report(1.0, f"Completado: {len(candidates)} candidatos de {n_detected} detecciones")
    summary = DiscoveryRunSummary(
        observation_id=observation.observation_id,
        n_images=len(observation.images),
        n_detected=n_detected,
        n_artifact_rejected=n_rejected,
        n_candidates=len(candidates),
        n_known=sum(1 for c in candidates if c.identification_state.value == "KNOWN"),
        n_unmatched=sum(1 for c in candidates if c.identification_state.value == "UNMATCHED"),
        n_discovery_review=sum(1 for c in candidates if c.identification_state.value == "DISCOVERY_REVIEW"),
        wcs_status=tuple(wcs_statuses),
    )
    return candidates, summary
