"""Construcción del `AnomalyVector` de siete dimensiones a partir de las
evidencias REALMENTE producidas por los motores anteriores.

## Regla central: ninguna dimensión opaca

Cada dimensión es una `Quantity` con valor, unidad, método y notas
desmontables -- nunca un "score" sin procedencia. Y una dimensión solo
lleva valor si el motor correspondiente se ejecutó de verdad sobre esta
fuente: si no, queda `Quantity.not_available(...)` con el motivo
concreto, que es información útil para el revisor ("no se evaluó porque
solo hay una época"), no un hueco silencioso.

Las siete dimensiones y de dónde sale cada una:

| dimensión      | motor que la alimenta                      |
|----------------|--------------------------------------------|
| photometric    | fotometría de apertura vs. campo           |
| morphological  | caracterización (FWHM/elongación vs. campo)|
| spectral       | relación entre bandas medida               |
| temporal       | TemporalEvidence (varias épocas)           |
| astrometric    | MotionEvidence (varias épocas)             |
| spatial        | motor espacial por población               |
| physical       | consistencias físicas internas             |
"""
from __future__ import annotations

import math

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence
from astrophysics_suite.physics.constraints import ConsistencyResult, physical_tension_quantity

ENGINE_NAME = "anomaly.vector"
ENGINE_VERSION = "1.0"


def _morphological_anomaly(characterization: CharacterizationResult, field_median_fwhm: float | None, field_scatter: float | None) -> Quantity:
    """Cuánto se aparta la forma de esta fuente de la PSF del campo, en
    sigmas reales de la dispersión medida del propio campo -- no un
    umbral arbitrario."""
    if characterization.fwhm is None or not characterization.fwhm.is_available or characterization.fwhm.value is None:
        return Quantity.not_available(unit="sigma", method=ENGINE_NAME, reference="sin FWHM medida para esta fuente")
    if field_median_fwhm is None or field_scatter is None or field_scatter <= 0:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="sin referencia de PSF del campo (hacen falta varias fuentes caracterizadas para medir su dispersión)",
        )
    z = (float(characterization.fwhm.value) - field_median_fwhm) / field_scatter
    return Quantity(
        value=abs(z), error=None, unit="sigma", kind=ValueKind.OBSERVED, method="fwhm_versus_field_psf_scatter",
        notes=(f"FWHM {characterization.fwhm.value:.2f} px frente a {field_median_fwhm:.2f} ± {field_scatter:.2f} px del campo",),
    )


def _spectral_anomaly(
    characterization: CharacterizationResult, expected_band_ratios: dict[str, float] | None,
) -> Quantity:
    """Cuánto se aparta una relación entre bandas MEDIDA de la que se
    ESPERA para ese tipo de objeto.

    Sin una expectativa, no hay anomalía que calcular: el valor absoluto
    de una relación no es anómalo por sí mismo (una relación OIII/Hα de
    1,8 es normalísima en un resto de supernova y rarísima en una región
    HII -- el número solo significa algo contra una referencia). Antes
    este cálculo devolvía |log10(ratio)|, que marcaba como "anómala"
    cualquier relación distinta de 1: un falso positivo sistemático."""
    ratios = {name: q for name, q in characterization.band_ratios.items() if q.is_available and q.value is not None and q.value > 0}
    if not ratios:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="sin relaciones entre bandas medidas (requiere fotometría de la misma fuente en dos o más filtros)",
        )
    if not expected_band_ratios:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference=(
                f"hay relaciones medidas ({', '.join(sorted(ratios))}) pero ninguna expectativa con la que compararlas: "
                f"una relación solo es anómala frente a la esperada para su tipo de objeto"
            ),
        )

    best: tuple[float, str, Quantity, float] | None = None
    for name, quantity in ratios.items():
        expected = expected_band_ratios.get(name)
        if expected is None or expected <= 0:
            continue
        error = float(quantity.error) if quantity.error is not None and quantity.error > 0 else None
        if error is None:
            continue
        z = abs(float(quantity.value) - expected) / error
        if best is None or z > best[0]:
            best = (z, name, quantity, expected)

    if best is None:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="las relaciones medidas no tienen incertidumbre o no hay expectativa para ellas: no se puede expresar la desviación en sigmas",
        )
    z, name, quantity, expected = best
    return Quantity(
        value=z, error=None, unit="sigma", kind=ValueKind.OBSERVED, method="band_ratio_versus_expected",
        notes=(f"{name} medida {quantity.value:.4f} ± {quantity.error:.4f} frente a la esperada {expected:.4f}",),
    )


def _photometric_anomaly(
    characterization: CharacterizationResult, expected_band_flux: dict[str, Quantity] | None,
) -> Quantity:
    """Cuánto se aparta el flujo MEDIDO del ESPERADO (p. ej. el que
    correspondería a la magnitud de su contrapartida de catálogo).

    Sin expectativa no hay anomalía. Antes esta función devolvía
    flujo/incertidumbre, que es la SIGNIFICANCIA DE DETECCIÓN, no una
    anomalía: habría marcado como fotométricamente anómala a cualquier
    estrella brillante del campo -- exactamente el falso positivo que
    este proyecto no se puede permitir."""
    fluxes = {band: q for band, q in characterization.band_flux.items() if q.is_available and q.value is not None}
    if not fluxes:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="sin flujo medido para esta fuente (la fotometría de apertura no se ejecutó o no produjo un flujo válido)",
        )
    if not expected_band_flux:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference=(
                f"hay flujo medido ({', '.join(sorted(fluxes))}) pero ningún flujo esperado con el que compararlo "
                f"(requiere una contrapartida de catálogo con magnitud, o un punto cero fotométrico ajustado)"
            ),
        )

    best: tuple[float, str, Quantity, Quantity] | None = None
    for band, quantity in fluxes.items():
        expected = expected_band_flux.get(band)
        if expected is None or not expected.is_available or expected.value is None:
            continue
        measured_error = float(quantity.error) if quantity.error is not None and quantity.error > 0 else None
        if measured_error is None:
            continue
        expected_error = float(expected.error) if expected.error is not None and expected.error > 0 else 0.0
        # La incertidumbre de `expected` (p. ej. la del punto cero
        # fotométrico que la produjo) se combina en cuadratura con la
        # medida -- antes se ignoraba por completo, lo que podía inflar
        # la significancia declarada frente a una expectativa que
        # también tiene su propio margen de error real.
        combined_error = math.sqrt(measured_error**2 + expected_error**2)
        z = abs(float(quantity.value) - float(expected.value)) / combined_error
        if best is None or z > best[0]:
            best = (z, band, quantity, expected)

    if best is None:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="el flujo medido no lleva incertidumbre o no hay flujo esperado para su banda: no se puede expresar la desviación en sigmas",
        )
    z, band, quantity, expected = best
    return Quantity(
        value=z, error=None, unit="sigma", kind=ValueKind.OBSERVED, method="flux_versus_expected",
        notes=(
            f"banda {band}: medido {quantity.value:.4g} ± {quantity.error:.4g} {quantity.unit}, "
            f"esperado {expected.value:.4g} ± {(expected.error or 0.0):.4g} {expected.unit}",
        ),
    )


def _temporal_anomaly(temporal: TemporalEvidence | None) -> Quantity:
    if temporal is None:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="el motor temporal no se ejecutó para esta fuente (hace falta más de una época de la misma zona del cielo)",
        )
    change = temporal.brightness_change
    if change is None or not change.is_available or change.value is None or change.error is None or change.error <= 0:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference=f"el motor temporal corrió con {temporal.n_epochs} época(s) pero no produjo un cambio de brillo con incertidumbre",
        )
    significance = abs(float(change.value) / float(change.error))
    return Quantity(
        value=significance, error=None, unit="sigma", kind=ValueKind.OBSERVED, method="brightness_slope_significance",
        notes=(f"pendiente {change.value:.4g} ± {change.error:.4g} {change.unit} sobre {temporal.n_epochs} épocas",),
    )


def _astrometric_anomaly(motion: MotionEvidence | None) -> Quantity:
    if motion is None:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="el motor de movimiento no se ejecutó para esta fuente (hace falta más de una época con WCS)",
        )
    pm = motion.pm_total
    if pm is None or not pm.is_available or pm.value is None or pm.error is None or pm.error <= 0:
        return Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference=f"el motor de movimiento corrió con {motion.n_epochs_used} época(s) pero no produjo un movimiento propio con incertidumbre",
        )
    significance = abs(float(pm.value) / float(pm.error))
    return Quantity(
        value=significance, error=None, unit="sigma", kind=ValueKind.OBSERVED, method="proper_motion_significance",
        notes=(f"movimiento propio {pm.value:.4g} ± {pm.error:.4g} {pm.unit} sobre {motion.n_epochs_used} épocas",),
    )


def build_anomaly_vector(
    *,
    detection_id: str,
    characterization: CharacterizationResult,
    consistency: ConsistencyResult | None = None,
    temporal: TemporalEvidence | None = None,
    motion: MotionEvidence | None = None,
    field_median_fwhm_px: float | None = None,
    field_fwhm_scatter_px: float | None = None,
    spatial: Quantity | None = None,
    expected_band_flux: dict[str, Quantity] | None = None,
    expected_band_ratios: dict[str, float] | None = None,
) -> AnomalyVector:
    """Ensambla las siete dimensiones. Las que no se pudieron calcular
    llegan como NO DISPONIBLE con su motivo real, nunca ausentes sin
    explicación.

    `expected_band_flux`/`expected_band_ratios` son las expectativas
    contra las que se mide una anomalía. Sin ellas, esas dimensiones
    quedan NO DISPONIBLE: una medida sin referencia no es anómala."""
    physical = (
        physical_tension_quantity(consistency) if consistency is not None
        else Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="no se evaluaron consistencias físicas (sin observables físicos para esta fuente)",
        )
    )
    if spatial is None:
        spatial = Quantity.not_available(
            unit="sigma", method=ENGINE_NAME,
            reference="el motor espacial trabaja sobre la población completa de detecciones y no se ejecutó en este análisis",
        )

    return AnomalyVector.create(
        detection_id=detection_id,
        photometric=_photometric_anomaly(characterization, expected_band_flux),
        morphological=_morphological_anomaly(characterization, field_median_fwhm_px, field_fwhm_scatter_px),
        spectral=_spectral_anomaly(characterization, expected_band_ratios),
        temporal=_temporal_anomaly(temporal),
        astrometric=_astrometric_anomaly(motion),
        spatial=spatial,
        physical=physical,
    )
