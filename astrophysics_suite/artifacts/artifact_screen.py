"""Motor de rechazo de artefactos -- separa DETECCIÓN REAL de ARTEFACTO
antes de que nada llegue a ser un `Candidate`.

## De dónde salen los criterios (ninguno inventado)

Todos los detectores de este módulo consumen medidas que
`photometry/quality.py` YA obtiene de los píxeles reales
(`measure_source_quality`: `fwhm_px`, `ellipticity`, `sharpness`,
`snr_local`, `saturated`, `isolated`, `n_peaks_in_stamp`, `peak_adu`,
`noise_adu`). No se vuelve a medir nada por una segunda vía: el
`CharacterizationResult` es la única fuente de verdad de esas
magnitudes, precisamente para no acabar con dos valores incompatibles
de la misma propiedad.

Algunos criterios necesitan la POBLACIÓN de detecciones de la imagen, no
una sola fuente (p. ej. "esta FWHM es anómala *comparada con el campo*").
Eso se resuelve con `FieldStatistics`, que se calcula una vez por imagen
y se pasa a cada detección -- el motor es explícitamente de dos niveles
(por población y por detección), no se fuerza todo a la misma firma.

## Qué NO hace

`REFLECTION`, `DONUT`, `GRADIENT`, `STACKING_RESIDUAL` y
`PROCESSING_ARTIFACT` no tienen aquí un criterio que el dato disponible
justifique, así que se emiten explícitamente como NO DISPONIBLE
(`ArtifactCheck` con `confidence=Quantity.not_available(...)` y el motivo
concreto), nunca como "comprobado y limpio". `REGISTRATION_ERROR` sí se
evalúa, pero solo en modo multiépoca, donde existe dispersión de
posición real que medir (ver `discovery/source_tracks.py`); en una sola
época se declara no disponible por el mismo criterio.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

from astrophysics_suite.core.enums import ArtifactKind, ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import ArtifactCheck
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection

ENGINE_NAME = "artifacts.artifact_screen"
ENGINE_VERSION = "1.0"

#: Umbrales explícitos. No son "constantes mágicas": cada uno se justifica
#: en el docstring del detector que lo usa, y todos son parámetros de
#: `screen_detection`, así que un llamador puede ajustarlos con criterio.
DEFAULT_TRAIL_ELONGATION = 4.0
DEFAULT_COSMIC_RAY_FWHM_RATIO = 0.6
DEFAULT_PSF_DEFECT_FWHM_RATIO = 2.0
DEFAULT_MIN_SNR = 3.0
DEFAULT_HOT_PIXEL_FWHM_PX = 1.2


@dataclass(frozen=True)
class FieldStatistics:
    """Estadística de la POBLACIÓN de fuentes de una imagen -- necesaria
    para los criterios que solo tienen sentido comparando una fuente con
    su campo (una FWHM de 1,1 px no es anómala en sí: lo es si el resto
    del campo está en 3,5 px).

    `median_fwhm_px` es `None` cuando no hubo suficientes fuentes
    caracterizadas para establecer una referencia fiable -- en ese caso
    los detectores que dependen de ella se declaran NO DISPONIBLE en vez
    de usar un valor por defecto inventado."""

    n_sources: int
    median_fwhm_px: float | None
    fwhm_scatter_px: float | None

    @property
    def has_psf_reference(self) -> bool:
        return self.median_fwhm_px is not None and self.median_fwhm_px > 0.0


def compute_field_statistics(characterizations: list[CharacterizationResult], *, min_sources: int = 5) -> FieldStatistics:
    """Referencia de PSF del campo a partir de las fuentes ya
    caracterizadas. Con menos de `min_sources` medidas reales no se
    establece referencia: una mediana de 2 o 3 estrellas no distingue
    "el campo tiene esta PSF" de "estas dos fuentes son raras"."""
    fwhm_values = [
        c.fwhm.value for c in characterizations
        if c.fwhm is not None and c.fwhm.is_available and c.fwhm.value is not None and math.isfinite(c.fwhm.value) and c.fwhm.value > 0
    ]
    if len(fwhm_values) < min_sources:
        return FieldStatistics(n_sources=len(fwhm_values), median_fwhm_px=None, fwhm_scatter_px=None)
    array = np.asarray(fwhm_values, dtype=float)
    median = float(np.median(array))
    scatter = float(np.median(np.abs(array - median)) * 1.4826)
    return FieldStatistics(n_sources=len(fwhm_values), median_fwhm_px=median, fwhm_scatter_px=scatter)


@dataclass(frozen=True)
class ArtifactScreenResult:
    """Resultado completo del cribado: TODAS las categorías evaluadas
    (incluidas las no disponibles, con su motivo), más el veredicto."""

    checks: tuple[ArtifactCheck, ...]
    rejected: bool
    """`True` si alguna comprobación con criterio real marcó artefacto --
    en ese caso la detección NO debe convertirse en `Candidate`."""
    reason: str

    @property
    def flagged_kinds(self) -> tuple[ArtifactKind, ...]:
        return tuple(check.kind for check in self.checks if check.flagged)


def _extra_value(characterization: CharacterizationResult, key: str) -> float | None:
    quantity = characterization.extra.get(key)
    if quantity is None or not quantity.is_available or quantity.value is None:
        return None
    return float(quantity.value)


def _not_available(kind: ArtifactKind, reason: str) -> ArtifactCheck:
    return ArtifactCheck(
        kind=kind,
        flagged=False,
        confidence=Quantity.not_available(unit="dimensionless", method=ENGINE_NAME, reference=reason),
        notes=f"No evaluable: {reason}",
    )


def _flag(kind: ArtifactKind, *, flagged: bool, confidence: float, method: str, notes: str) -> ArtifactCheck:
    return ArtifactCheck(
        kind=kind,
        flagged=flagged,
        confidence=Quantity(value=float(confidence), error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method=method),
        notes=notes,
    )


def screen_detection(
    detection: Detection,
    characterization: CharacterizationResult,
    field: FieldStatistics,
    *,
    trail_elongation: float = DEFAULT_TRAIL_ELONGATION,
    cosmic_ray_fwhm_ratio: float = DEFAULT_COSMIC_RAY_FWHM_RATIO,
    psf_defect_fwhm_ratio: float = DEFAULT_PSF_DEFECT_FWHM_RATIO,
    min_snr: float = DEFAULT_MIN_SNR,
    hot_pixel_fwhm_px: float = DEFAULT_HOT_PIXEL_FWHM_PX,
    position_scatter_arcsec: float | None = None,
    registration_rms_arcsec: float | None = None,
) -> ArtifactScreenResult:
    """Evalúa TODAS las categorías de `ArtifactKind` para una detección.

    `position_scatter_arcsec`/`registration_rms_arcsec` solo existen en
    modo multiépoca; sin ellos, `REGISTRATION_ERROR` se declara no
    disponible en vez de darse por limpio."""
    checks: list[ArtifactCheck] = []
    reasons: list[str] = []

    fwhm = characterization.fwhm.value if (characterization.fwhm is not None and characterization.fwhm.is_available) else None
    elongation = characterization.elongation.value if (characterization.elongation is not None and characterization.elongation.is_available) else None
    snr = _extra_value(characterization, "snr_local")
    if snr is None and math.isfinite(detection.peak_snr):
        snr = float(detection.peak_snr)
    saturated = _extra_value(characterization, "saturated")
    n_peaks = _extra_value(characterization, "n_peaks_in_stamp")

    # --- SATURACIÓN: medida directa contra el nivel de saturación real ---
    if saturated is None:
        checks.append(_not_available(
            ArtifactKind.SATURATION,
            "la caracterización no pudo determinar saturación (sin nivel de saturación conocido o cutout no medible)",
        ))
    else:
        is_saturated = saturated >= 0.5
        checks.append(_flag(
            ArtifactKind.SATURATION, flagged=is_saturated, confidence=1.0 if is_saturated else 0.0,
            method="peak_above_saturation_level",
            notes="El pico de la fuente alcanza el nivel de saturación: el flujo medido es un límite inferior, no una medida."
            if is_saturated else "Pico por debajo del nivel de saturación.",
        ))
        if is_saturated:
            reasons.append("saturada")

    # --- RUIDO: señal por debajo del mínimo para considerarla una fuente ---
    if snr is None:
        checks.append(_not_available(ArtifactKind.NOISE, "sin S/N local medible"))
    else:
        is_noise = snr < min_snr
        checks.append(_flag(
            ArtifactKind.NOISE, flagged=is_noise, confidence=min(1.0, max(0.0, (min_snr - snr) / min_snr)) if is_noise else 0.0,
            method="snr_local_below_threshold",
            notes=f"S/N local {snr:.2f} por debajo del mínimo {min_snr:.2f}: compatible con una fluctuación de ruido."
            if is_noise else f"S/N local {snr:.2f}, por encima del mínimo {min_snr:.2f}.",
        ))
        if is_noise:
            reasons.append(f"S/N {snr:.2f} < {min_snr:.2f}")

    # --- TRAZA DE SATÉLITE/AVIÓN: elongación extrema ---
    if elongation is None:
        checks.append(_not_available(ArtifactKind.SATELLITE_OR_AIRPLANE_TRAIL, "sin elongación medible"))
    else:
        is_trail = elongation >= trail_elongation
        checks.append(_flag(
            ArtifactKind.SATELLITE_OR_AIRPLANE_TRAIL, flagged=is_trail,
            confidence=min(1.0, elongation / (2.0 * trail_elongation)) if is_trail else 0.0,
            method="elongation_above_threshold",
            notes=f"Elongación {elongation:.2f} >= {trail_elongation:.2f}: geometría de traza, no de fuente puntual."
            if is_trail else f"Elongación {elongation:.2f}, compatible con una fuente no alargada.",
        ))
        if is_trail:
            reasons.append(f"elongación {elongation:.2f}")

    # --- PÍXEL CALIENTE: perfil más estrecho que un solo píxel resuelto ---
    if fwhm is None:
        checks.append(_not_available(ArtifactKind.HOT_PIXEL, "sin FWHM medible"))
    else:
        is_hot = fwhm <= hot_pixel_fwhm_px
        checks.append(_flag(
            ArtifactKind.HOT_PIXEL, flagged=is_hot, confidence=1.0 if is_hot else 0.0,
            method="fwhm_below_single_pixel",
            notes=f"FWHM {fwhm:.2f} px <= {hot_pixel_fwhm_px:.2f} px: no hay perfil real, compatible con un píxel caliente."
            if is_hot else f"FWHM {fwhm:.2f} px, con perfil resuelto.",
        ))
        if is_hot:
            reasons.append(f"FWHM {fwhm:.2f} px (píxel caliente)")

    # --- RAYO CÓSMICO y DEFECTO DE PSF: ambos frente a la PSF del campo ---
    if fwhm is None or not field.has_psf_reference:
        missing = "sin FWHM medible" if fwhm is None else (
            f"sin referencia de PSF del campo (solo {field.n_sources} fuente(s) caracterizada(s))"
        )
        checks.append(_not_available(ArtifactKind.COSMIC_RAY, missing))
        checks.append(_not_available(ArtifactKind.PSF_DEFECT, missing))
    else:
        ratio = fwhm / field.median_fwhm_px
        is_cosmic = ratio <= cosmic_ray_fwhm_ratio
        checks.append(_flag(
            ArtifactKind.COSMIC_RAY, flagged=is_cosmic, confidence=1.0 - ratio if is_cosmic else 0.0,
            method="fwhm_versus_field_psf",
            notes=f"FWHM {fwhm:.2f} px es {ratio:.2f}x la del campo ({field.median_fwhm_px:.2f} px): más afilada que la PSF, "
                  f"compatible con un impacto de rayo cósmico." if is_cosmic
            else f"FWHM {fwhm:.2f} px = {ratio:.2f}x la del campo, compatible con la PSF real.",
        ))
        if is_cosmic:
            reasons.append(f"FWHM {ratio:.2f}x la del campo (rayo cósmico)")

        is_defect = ratio >= psf_defect_fwhm_ratio
        checks.append(_flag(
            ArtifactKind.PSF_DEFECT, flagged=is_defect, confidence=min(1.0, ratio / (2.0 * psf_defect_fwhm_ratio)) if is_defect else 0.0,
            method="fwhm_versus_field_psf",
            notes=f"FWHM {fwhm:.2f} px es {ratio:.2f}x la del campo: perfil muy ensanchado (desenfoque, arrastre o mezcla de fuentes)."
            if is_defect else f"FWHM coherente con la PSF del campo ({ratio:.2f}x).",
        ))
        if is_defect:
            reasons.append(f"FWHM {ratio:.2f}x la del campo (PSF defectuosa)")

    # --- ERROR DE REGISTRO: solo tiene sentido con varias épocas ---
    if position_scatter_arcsec is None or registration_rms_arcsec is None:
        checks.append(_not_available(
            ArtifactKind.REGISTRATION_ERROR,
            "requiere varias épocas: sin dispersión de posición ni RMS de registro que comparar",
        ))
    else:
        is_registration = position_scatter_arcsec > 3.0 * max(registration_rms_arcsec, 1e-9)
        checks.append(_flag(
            ArtifactKind.REGISTRATION_ERROR, flagged=is_registration,
            confidence=min(1.0, position_scatter_arcsec / (6.0 * max(registration_rms_arcsec, 1e-9))) if is_registration else 0.0,
            method="position_scatter_versus_registration_rms",
            notes=f"Dispersión de posición {position_scatter_arcsec:.3f}\" frente a un RMS de registro de "
                  f"{registration_rms_arcsec:.3f}\": incompatible con la misma fuente bien registrada."
            if is_registration else f"Dispersión de posición {position_scatter_arcsec:.3f}\" coherente con el registro.",
        ))
        if is_registration:
            reasons.append("dispersión de posición incompatible con el registro")

    # --- Categorías sin criterio justificable con los datos disponibles ---
    for kind, why in (
        (ArtifactKind.REFLECTION, "no hay un criterio validado para reflejos con los observables disponibles por fuente"),
        (ArtifactKind.DONUT, "detectar donuts de desenfoque requiere analizar la forma del perfil radial completo, no implementado"),
        (ArtifactKind.GRADIENT, "los gradientes son una propiedad del fondo de la imagen, no de una fuente; no evaluado aquí"),
        (ArtifactKind.STACKING_RESIDUAL, "requiere los fotogramas individuales del apilado, que el pipeline no recibe en esta ruta"),
        (ArtifactKind.PROCESSING_ARTIFACT, "no hay un criterio validado que distinga un artefacto de procesado de una fuente real"),
    ):
        checks.append(_not_available(kind, why))

    # `OTHER` solo se marca si la fuente tiene varios picos en el cutout:
    # es una medida real (`n_peaks_in_stamp`), pero no identifica QUÉ es.
    if n_peaks is None:
        checks.append(_not_available(ArtifactKind.OTHER, "sin recuento de picos en el cutout"))
    else:
        blended = n_peaks > 1
        checks.append(_flag(
            ArtifactKind.OTHER, flagged=False, confidence=0.0, method="connected_components_at_30pct_peak",
            notes=f"{int(n_peaks)} pico(s) en el cutout: fuente mezclada con vecina, la fotometría de apertura puede estar contaminada."
            if blended else "Un solo pico en el cutout: fuente aislada.",
        ))

    rejected = any(check.flagged for check in checks)
    reason = "; ".join(reasons) if reasons else "Ninguna comprobación de artefacto con criterio real marcó esta detección."
    return ArtifactScreenResult(checks=tuple(checks), rejected=rejected, reason=reason)
