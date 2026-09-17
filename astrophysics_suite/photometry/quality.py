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

    # Todas las medidas reales que `measure_source_quality` ya calcula se
    # propagan aquí: antes se descartaban `saturated`, `isolated`,
    # `n_peaks_in_stamp`, `peak_adu`, `background_adu` y `noise_adu`, que son
    # exactamente los observables que necesita el motor de artefactos
    # (`artifacts/artifact_screen.py`). Perderlos obligaba a volver a
    # medirlos por otra vía, con el riesgo real de acabar con dos medidas
    # incompatibles de la misma propiedad. `CharacterizationResult` es la
    # ÚNICA fuente de verdad de estas magnitudes por fuente.
    extra: dict[str, Quantity] = {}

    def _observed(key: str, unit: str, method: str) -> None:
        value = raw.get(key)
        if value is not None and math.isfinite(float(value)):
            extra[key] = Quantity(value=float(value), error=None, unit=unit, kind=ValueKind.OBSERVED, method=method)

    _observed("sharpness", "dimensionless", "peak_over_central_mean")
    _observed("snr_local", "dimensionless", "peak_over_local_noise")
    _observed("peak_adu", "adu", "cutout_peak")
    _observed("background_adu", "adu", "cutout_background")
    _observed("noise_adu", "adu", "cutout_noise")
    _observed("n_peaks_in_stamp", "count", "connected_components_at_30pct_peak")

    # Booleanos reales medidos sobre los píxeles: se conservan como Quantity
    # 0/1 para que viajen por el mismo contrato que el resto y lleguen con
    # su método explícito, en vez de perderse por no ser numéricos.
    for key, method in (("saturated", "peak_above_saturation_level"), ("isolated", "single_component_at_30pct_peak")):
        value = raw.get(key)
        if value is not None:
            extra[key] = Quantity(value=1.0 if value else 0.0, error=None, unit="boolean", kind=ValueKind.OBSERVED, method=method)

    return CharacterizationResult.create(
        detection_id=detection.detection_id,
        position=detection.position,
        provenance=provenance,
        fwhm=fwhm_quantity,
        elongation=elongation_quantity,
        extra=extra,
    )
