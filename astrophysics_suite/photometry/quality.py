"""Medición de calidad por fuente -> `CharacterizationResult`.

Convención de forma: igual que en `detection/point_sources.py`, la
elipticidad heredada (`1 - b/a`) se convierte a la convención de
elongación de la Fase 4 (`sqrt(l1/l2)` = `1/(1-ellipticity)`).
"""
from __future__ import annotations

import math

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import measure_source_quality as _legacy_measure_source_quality

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection

ENGINE_NAME = "photometry.quality"
ENGINE_VERSION = "1.0"


def characterize_point_source(
    loaded_image: LoadedImage,
    detection: Detection,
    *,
    cutout_size: int = 25,
    gain: float = 1.0,
    saturation_level: float | None = None,
    pipeline_version: str = "",
) -> CharacterizationResult:
    raw = _legacy_measure_source_quality(
        loaded_image.legacy_image.data,
        detection.position.x_px,
        detection.position.y_px,
        cutout_size=cutout_size,
        gain=gain,
        saturation_level=saturation_level,
    )
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)

    if raw.get("state") != "OBSERVABLE":
        return CharacterizationResult.create(
            detection_id=detection.detection_id,
            position=detection.position,
            provenance=provenance,
            extra={
                "quality_measurement": Quantity.not_available(
                    unit="dimensionless", method="measure_source_quality", reference=raw.get("error", "sin estado OBSERVABLE")
                )
            },
        )

    fwhm = raw.get("fwhm_px")
    ellipticity = raw.get("ellipticity")
    elongation_quantity = None
    fwhm_quantity = None
    if fwhm is not None and math.isfinite(fwhm):
        fwhm_quantity = Quantity(value=fwhm, error=None, unit="px", kind=ValueKind.OBSERVED, method="second_moments")
    if ellipticity is not None and math.isfinite(ellipticity) and ellipticity < 0.999:
        elongation_quantity = Quantity(value=1.0 / (1.0 - ellipticity), error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="second_moments")

    extra = {}
    if raw.get("sharpness") is not None and math.isfinite(raw["sharpness"]):
        extra["sharpness"] = Quantity(value=raw["sharpness"], error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="peak_over_central_mean")
    if math.isfinite(raw.get("snr_local", float("nan"))):
        extra["snr_local"] = Quantity(value=raw["snr_local"], error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="peak_over_local_noise")

    return CharacterizationResult.create(
        detection_id=detection.detection_id,
        position=detection.position,
        provenance=provenance,
        fwhm=fwhm_quantity,
        elongation=elongation_quantity,
        extra=extra,
    )
