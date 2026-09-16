"""Detección de fuentes puntuales -> `Detection` (Fase 4).

Traduce la salida de `legacy...detect_point_sources()` (array (N,3)
[x, y, flux], contrato verificado en la Fase 3 --
tests/regression/test_historical_contracts.py) y de
`legacy...enrich_star_rows()` (FWHM/elipticidad reales por fuente, vía
momentos de segundo orden -- no valores inventados) a `Detection`.

Conversión de convención de forma: `enrich_star_rows` devuelve
`ellipticity = 1 - sqrt(l2/l1)` (0 = circular, ->1 = muy alargada);
`MorphologySummary.elongation` sigue la convención ya usada en
`legacy...detect_discovery_sources()` (`sqrt(l1/l2)`, 1.0 = circular).
Son la misma información geométrica en dos convenciones distintas --
mezclarlas sin convertir sería exactamente la clase de bug de contrato
que motivó esta reingeniería (ver docs/audit/01-..., seccion 3.3).
"""
from __future__ import annotations

import math

import numpy as np

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import (
    detect_point_sources as _legacy_detect_point_sources,
)
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import enrich_star_rows as _legacy_enrich_star_rows
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import estimate_background as _legacy_estimate_background

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition

ENGINE_NAME = "detection.point_sources"
ENGINE_VERSION = "1.0"
DETECTION_METHOD = "DAOStarFinder"


def _elongation_from_legacy_ellipticity(ellipticity: float, fallback: float = 1.0) -> float:
    if not math.isfinite(ellipticity) or ellipticity >= 0.999:
        return fallback
    return 1.0 / (1.0 - ellipticity)


def _finite_or(value: float, fallback: float) -> float:
    return value if math.isfinite(value) else fallback


def detect_point_sources(
    loaded_image: LoadedImage,
    *,
    observation_id: str,
    band: str,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_sources: int = 3000,
    pipeline_version: str = "",
) -> list[Detection]:
    """Detecta fuentes puntuales en una imagen ya cargada (`io.fits_loader.
    load_image`) y las devuelve como `Detection` tipados, con posición
    celeste cuando la imagen tiene WCS."""
    fits_image = loaded_image.legacy_image
    bkg = _legacy_estimate_background(fits_image.data)
    raw_sources = _legacy_detect_point_sources(
        fits_image.data, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
    )
    enriched_rows = _legacy_enrich_star_rows(fits_image, raw_sources, bkg)

    provenance = Provenance.now(
        pipeline_version=pipeline_version,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        model_id=DETECTION_METHOD,
    )

    detections: list[Detection] = []
    for row in enriched_rows:
        x_px, y_px = row["x_px"], row["y_px"]
        ra_deg = dec_deg = None
        if fits_image.wcs is not None:
            ra_arr, dec_arr = fits_image.pixel_to_world([x_px], [y_px])
            if math.isfinite(ra_arr[0]) and math.isfinite(dec_arr[0]):
                ra_deg, dec_deg = float(ra_arr[0]), float(dec_arr[0])
        position = SkyPosition(x_px=x_px, y_px=y_px, ra_deg=ra_deg, dec_deg=dec_deg)

        fwhm_measured = _finite_or(row["fwhm_px"], fwhm_px)
        elongation = _elongation_from_legacy_ellipticity(row["ellipticity"])
        compactness = _finite_or(row["sharpness_index"], 0.0)
        area_px = math.pi * (fwhm_measured / 2.0) ** 2

        morphology = MorphologySummary(
            morphology_class=MorphologyClass.POINT_SOURCE,
            area_px=area_px,
            elongation=elongation,
            compactness=compactness,
            fwhm_px=fwhm_measured,
        )

        detections.append(
            Detection.create(
                detection_id=f"{observation_id}-PT-{row['det_id']:05d}",
                observation_id=observation_id,
                position=position,
                morphology=morphology,
                bands=(band,),
                peak_snr=_finite_or(row["snr_peak"], 0.0),
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
    bkg = _legacy_estimate_background(array)
    raw_sources = _legacy_detect_point_sources(
        array, bkg, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
    )
    return [(float(x), float(y), float(flux)) for x, y, flux in raw_sources]
