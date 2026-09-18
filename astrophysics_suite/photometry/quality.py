"""Medición de calidad por fuente -> `CharacterizationResult`.

Convención de forma: igual que en `detection/point_sources.py`, la
elipticidad heredada (`1 - b/a`) se convierte a la convención de
elongación de la Fase 4 (`sqrt(l1/l2)` = `1/(1-ellipticity)`).
"""
from __future__ import annotations

import math

import numpy as np

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import measure_source_quality as _legacy_measure_source_quality

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection
from astrophysics_suite.photometry.aperture import aperture_photometry

ENGINE_NAME = "photometry.quality"
ENGINE_VERSION = "1.0"

#: Radio de apertura como múltiplo del FWHM real medido -- ~3x FWHM
#: captura ~99% del flujo de un perfil gaussiano (Howell, *Handbook of
#: CCD Astronomy*, cap. 5), en vez de un radio fijo elegido sin mirar la
#: PSF real de esta fuente. Los anillos de cielo escalan con el mismo
#: radio, de forma que se reducen exactamente a los valores por defecto
#: del proceso manual de apertura (`qt_app/processes/registry.py`:
#: radio 6 px, cielo 12-18 px) cuando el FWHM implica ~6 px de apertura.
_APERTURE_RADIUS_FWHM_FACTOR = 3.0
_MIN_APERTURE_RADIUS_PX = 3.0


def _measure_aperture_flux(data, x_px: float, y_px: float, fwhm_px: float) -> Quantity | None:
    """Fotometría de apertura real (`photometry/aperture.py`) en torno a
    una fuente ya caracterizada -- mismo modelo de incertidumbre
    (ruido de Poisson aproximado sobre los propios datos) que ya usa en
    producción el proceso manual de apertura, para no acabar con dos
    modelos de ruido incompatibles para la misma cámara.

    Una apertura que se solapa parcialmente con el borde de la imagen SÍ
    se mide (con menos píxeles efectivos, pero reales -- `aperture_photometry`
    recorta la cobertura a la imagen real, nunca inventa píxeles fuera de
    ella). Solo devuelve `None` cuando no hay geometría real que medir --
    la fuente cae completamente fuera de la imagen -- nunca un flujo
    inventado."""
    radius = max(_APERTURE_RADIUS_FWHM_FACTOR * fwhm_px, _MIN_APERTURE_RADIUS_PX)
    sky_r_in, sky_r_out = 2.0 * radius, 3.0 * radius
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    try:
        measurement = aperture_photometry(
            data, uncertainty, x_px, y_px, radii=[radius], sky_r_in=sky_r_in, sky_r_out=sky_r_out,
        )[0]
    except (ValueError, IndexError):
        return None
    if measurement.n_pixels <= 0:
        return None
    return Quantity(
        value=measurement.net_flux, error=measurement.net_flux_uncertainty, unit="adu", kind=ValueKind.OBSERVED,
        method="aperture_photometry",
        notes=(f"apertura {radius:.2f} px (3x FWHM), cielo {sky_r_in:.2f}-{sky_r_out:.2f} px, "
               f"{measurement.n_pixels:.1f} px efectivos",),
    )


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

    # Flujo real de apertura -- sin FWHM medida no hay con qué dimensionar
    # una apertura con criterio (nunca un radio fijo a ciegas), así que se
    # deja sin medir en vez de adivinar. `band_flux` es lo que
    # `anomaly/vector.py` (dimensión fotométrica) y `Candidate.flux`
    # necesitan y que hasta ahora ninguna ruta de producción rellenaba.
    band_flux: dict[str, Quantity] = {}
    if fwhm_quantity is not None:
        flux_quantity = _measure_aperture_flux(
            loaded_image.legacy_image.data, detection.position.x_px, detection.position.y_px, fwhm_quantity.value,
        )
        if flux_quantity is not None:
            for band in detection.bands:
                band_flux[band] = flux_quantity

    return CharacterizationResult.create(
        detection_id=detection.detection_id,
        position=detection.position,
        provenance=provenance,
        fwhm=fwhm_quantity,
        elongation=elongation_quantity,
        band_flux=band_flux,
        extra=extra,
    )
