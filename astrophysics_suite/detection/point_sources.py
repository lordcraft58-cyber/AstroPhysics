"""Detección de fuentes puntuales -> `Detection` (Fase 4).

Traduce la salida de `detection.finder.find_point_sources()` (array
`(N,3)` `[x, y, flux]`, contrato verificado desde la Fase 3 --
`tests/regression/test_historical_contracts.py`) y de
`detection.finder.enrich_detections()` (FWHM/elipticidad reales por
fuente, vía momentos de segundo orden -- no valores inventados) a
`Detection`.

Conversión de convención de forma: `enrich_detections` devuelve
`ellipticity = 1 - sqrt(l2/l1)` (0 = circular, ->1 = muy alargada);
`MorphologySummary.elongation` sigue la convención ya usada en el
Discovery Engine (`sqrt(l1/l2)`, 1.0 = circular). Son la misma
información geométrica en dos convenciones distintas -- mezclarlas sin
convertir sería exactamente la clase de bug de contrato que motivó esta
reingeniería (ver docs/audit/01-..., seccion 3.3).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.detection.background import estimate_background
from astrophysics_suite.detection.finder import enrich_detections, find_point_sources
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition

ENGINE_NAME = "detection.point_sources"
ENGINE_VERSION = "1.0"
DETECTION_METHOD = "DAOStarFinder"


def _elongation_from_ellipticity(ellipticity: float, fallback: float = 1.0) -> float:
    if not math.isfinite(ellipticity) or ellipticity >= 0.999:
        return fallback
    return 1.0 / (1.0 - ellipticity)


def _finite_or(value: float, fallback: float) -> float:
    return value if math.isfinite(value) else fallback


def _saturate_adu_from_header(header: dict | None) -> float | None:
    """Valor real de saturación del sensor si la cabecera lo trae --
    nunca un valor inventado cuando no está."""
    if not header:
        return None
    try:
        value = float(header.get("SATURATE"))
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def detect_point_sources(
    loaded_image: LoadedImage,
    *,
    observation_id: str,
    band: str,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 3000,
    pipeline_version: str = "",
    image_index: int | None = None,
) -> list[Detection]:
    """Detecta fuentes puntuales en una imagen ya cargada (`io.fits_loader.
    load_image`) y las devuelve como `Detection` tipados, con posición
    celeste cuando la imagen tiene WCS.

    `row.det_id` es una etiqueta de componente conexa LOCAL a esta
    imagen (reinicia en cada llamada) -- sin `image_index`, dos imágenes
    de la misma `Observation` (p. ej. varias épocas o bandas) producen
    `detection_id` que COLISIONAN de verdad en cuanto ambas tienen una
    fuente con el mismo índice local, sobrescribiendo silenciosamente la
    de la primera en cualquier estructura indexada por `detection_id`
    (encontrado ejecutando el pipeline multiépoca real, no supuesto:
    ver docs/audit del cierre de fase). Con `image_index`, el
    `detection_id` es único dentro de toda la `Observation`; sin él, se
    conserva el formato anterior para no romper compatibilidad con
    llamadores existentes de una sola imagen."""
    fits_image = loaded_image.legacy_image
    bkg = estimate_background(fits_image.data)
    raw_sources = find_point_sources(
        fits_image.data, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
    )
    saturate_adu = _saturate_adu_from_header(fits_image.header)
    enriched_rows = enrich_detections(fits_image.data, bkg, raw_sources, saturate_adu=saturate_adu)

    provenance = Provenance.now(
        pipeline_version=pipeline_version,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        model_id=DETECTION_METHOD,
    )

    detections: list[Detection] = []
    for row in enriched_rows:
        x_px, y_px = row.x_px, row.y_px
        ra_deg = dec_deg = None
        if fits_image.wcs is not None:
            ra_arr, dec_arr = fits_image.pixel_to_world([x_px], [y_px])
            if math.isfinite(ra_arr[0]) and math.isfinite(dec_arr[0]):
                ra_deg, dec_deg = float(ra_arr[0]), float(dec_arr[0])
        position = SkyPosition(x_px=x_px, y_px=y_px, ra_deg=ra_deg, dec_deg=dec_deg)

        fwhm_measured = _finite_or(row.fwhm_px, fwhm_px)
        elongation = _elongation_from_ellipticity(row.ellipticity)
        compactness = _finite_or(row.sharpness_index, 0.0)
        area_px = math.pi * (fwhm_measured / 2.0) ** 2

        morphology = MorphologySummary(
            morphology_class=MorphologyClass.POINT_SOURCE,
            area_px=area_px,
            elongation=elongation,
            compactness=compactness,
            fwhm_px=fwhm_measured,
        )

        detection_id = (
            f"{observation_id}-IMG{image_index:03d}-PT-{row.det_id:05d}"
            if image_index is not None
            else f"{observation_id}-PT-{row.det_id:05d}"
        )
        detections.append(
            Detection.create(
                detection_id=detection_id,
                observation_id=observation_id,
                position=position,
                morphology=morphology,
                bands=(band,),
                peak_snr=_finite_or(row.snr_peak, 0.0),
                method=DETECTION_METHOD,
                provenance=provenance,
            )
        )
    return detections


def detect_point_sources_in_array(
    data: np.ndarray,
    *,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 200,
) -> list[tuple[float, float, float]]:
    """Detección automática de fuentes puntuales (mismo motor real,
    DAOStarFinder, que `detect_point_sources`) directamente sobre un
    array 2D en memoria -- sin pasar por `LoadedImage`/`Detection`, que
    exigen `observation_id`, banda y proveniencia (pensados para el
    Discovery Engine, no para un paso previo interactivo de fotometría).

    Devuelve `(x_px, y_px, flux_adu)` ordenado de más a menos brillante --
    la forma mínima que necesita un flujo de fotometría para ofrecer
    "detectar automáticamente" como alternativa al clic manual."""
    array = np.asarray(data, dtype=np.float64)
    bkg = estimate_background(array)
    raw_sources = find_point_sources(
        array, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
    )
    return [(float(x), float(y), float(flux)) for x, y, flux in raw_sources]


@dataclass(frozen=True)
class PSFCandidate:
    """Fuente detectada con las métricas locales (FWHM, elipticidad,
    nitidez, S/N de pico) que necesita una selección de estrellas de
    referencia para PSF (`pstselect`) -- a diferencia de
    `detect_point_sources_in_array`, que solo da posición y flujo bruto
    (suficiente para "haz clic por mí", no para juzgar si una fuente es
    una buena referencia)."""

    x: float
    y: float
    flux: float
    fwhm_px: float
    ellipticity: float
    """Convención de `enrich_detections`: 0 = circular, -> 1 = muy
    alargada."""
    sharpness: float
    snr: float


def detect_psf_candidates(
    data: np.ndarray,
    *,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 200,
) -> list[PSFCandidate]:
    """Detección automática enriquecida -- mismo motor que
    `detect_point_sources_in_array` (DAOStarFinder), pero con las métricas
    locales reales de `enrich_detections` (momentos de segundo orden, no un
    placeholder) que necesita `photometry.psf.select_psf_reference_stars`
    para aplicar los criterios de `pstselect` (aislamiento, redondez,
    señal/ruido). Sin cabecera FITS real disponible en este camino (array
    en memoria, no un archivo cargado), la detección de saturación de
    `enrich_detections` queda inactiva -- no se dispone del valor `SATURATE`
    real, así que no se inventa uno."""
    array = np.asarray(data, dtype=np.float64)
    bkg = estimate_background(array)
    raw_sources = find_point_sources(
        array, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
    )
    if raw_sources.size == 0:
        return []
    enriched_rows = enrich_detections(array, bkg, raw_sources, saturate_adu=None)
    return [
        PSFCandidate(
            x=row.x_px,
            y=row.y_px,
            flux=_finite_or(row.flux_adu, 0.0),
            fwhm_px=_finite_or(row.fwhm_px, fwhm_px),
            ellipticity=_finite_or(row.ellipticity, 0.0),
            sharpness=_finite_or(row.sharpness_index, 0.0),
            snr=_finite_or(row.snr_peak, 0.0),
        )
        for row in enriched_rows
    ]
