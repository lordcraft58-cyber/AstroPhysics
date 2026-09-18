"""Adaptador `Characterization` -> observables físicos.

## El hueco que cierra

`physics/inference.py` (y el motor heredado que envuelve) trabaja sobre
un `row: dict` con observables concretos (`oiii_ha_ratio`,
`offset_arcsec`, `radius_pc`, `velocity_kms`, `distance_pc`...). Nadie
en la ruta de producción construía ese `row`, así que el motor físico
existía y no se ejecutaba nunca sobre píxeles reales.

Este módulo construye ese `row` a partir de lo que los motores
anteriores han MEDIDO de verdad, y -- esto es lo importante -- declara
explícitamente qué observables NO están disponibles y por qué, en vez de
rellenarlos con valores plausibles. Un observable ausente desactiva los
modelos físicos que lo necesitan; nunca los activa con un número
inventado.

## Regla dura

Aquí no se calcula ninguna magnitud física nueva. Solo se traducen
medidas existentes a los nombres que el motor físico espera, y se
adjunta la distancia/escala que el usuario haya proporcionado
explícitamente. Si el usuario no da distancia, no hay `radius_pc`: una
separación angular no se convierte en parsecs por su cuenta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from astrophysics_suite.models.characterization import CharacterizationResult

ENGINE_NAME = "physics.observables"
ENGINE_VERSION = "1.0"


@dataclass(frozen=True)
class PhysicalObservables:
    """Los observables físicos realmente disponibles para una fuente, con
    el motivo concreto de cada ausencia."""

    row: dict[str, float]
    """Observables medidos, con los nombres que espera el motor físico."""
    unavailable: dict[str, str] = field(default_factory=dict)
    """`{observable: motivo}` -- lo que NO se pudo obtener y por qué.
    Nunca se rellena con un valor por defecto."""
    object_family: str = "unknown"

    @property
    def has_any(self) -> bool:
        return bool(self.row)

    def describe_gaps(self) -> str:
        if not self.unavailable:
            return "Todos los observables considerados están disponibles."
        return "; ".join(f"{name}: {why}" for name, why in sorted(self.unavailable.items()))


def _available(characterization: CharacterizationResult, attribute: str) -> float | None:
    quantity = getattr(characterization, attribute, None)
    if quantity is None or not quantity.is_available or quantity.value is None:
        return None
    value = float(quantity.value)
    return value if math.isfinite(value) else None


def _error_of(characterization: CharacterizationResult, attribute: str) -> float | None:
    quantity = getattr(characterization, attribute, None)
    if quantity is None or not quantity.is_available or quantity.error is None:
        return None
    error = float(quantity.error)
    return error if math.isfinite(error) and error > 0 else None


def build_physical_observables(
    characterization: CharacterizationResult,
    *,
    pixel_scale_arcsec: float | None = None,
    distance_pc: float | None = None,
    distance_err_pc: float | None = None,
    velocity_kms: float | None = None,
    velocity_err_kms: float | None = None,
    object_family: str = "unknown",
) -> PhysicalObservables:
    """Traduce lo medido a los observables del motor físico.

    `distance_pc` y `velocity_kms` NO se pueden derivar de una imagen:
    los aporta el usuario (o un catálogo) o no existen. Sin ellos, los
    modelos que dependen de ellos quedan desactivados con su motivo, que
    es el comportamiento correcto -- no una limitación que haya que
    disimular."""
    row: dict[str, float] = {}
    unavailable: dict[str, str] = {}

    # --- Relación de líneas: medida real entre bandas, si existe ---
    ratio_quantity = characterization.band_ratios.get("OIII/HA") or characterization.band_ratios.get("oiii_ha")
    if ratio_quantity is not None and ratio_quantity.is_available and ratio_quantity.value is not None:
        row["oiii_ha_ratio"] = float(ratio_quantity.value)
        if ratio_quantity.error is not None and math.isfinite(float(ratio_quantity.error)):
            row["ratio_err"] = float(ratio_quantity.error)
    else:
        unavailable["oiii_ha_ratio"] = (
            "no hay una relación OIII/Hα medida para esta fuente (requiere fotometría en ambas bandas sobre imágenes registradas)"
        )

    # --- Tamaño angular: de la FWHM medida y la escala de píxel real ---
    fwhm_px = _available(characterization, "fwhm")
    if fwhm_px is not None and pixel_scale_arcsec is not None and pixel_scale_arcsec > 0:
        row["offset_arcsec"] = fwhm_px * pixel_scale_arcsec
        fwhm_err_px = _error_of(characterization, "fwhm")
        if fwhm_err_px is not None:
            row["offset_err_arcsec"] = fwhm_err_px * pixel_scale_arcsec
    elif fwhm_px is None:
        unavailable["offset_arcsec"] = "sin FWHM medida para esta fuente"
    else:
        unavailable["offset_arcsec"] = "sin escala de píxel conocida (la imagen no tiene WCS ni PIXSCALE)"

    # --- Distancia: solo la que aporte el usuario ---
    if distance_pc is not None and math.isfinite(distance_pc) and distance_pc > 0:
        row["distance_pc"] = float(distance_pc)
        if distance_err_pc is not None and math.isfinite(distance_err_pc) and distance_err_pc > 0:
            row["distance_err_pc"] = float(distance_err_pc)
    else:
        unavailable["distance_pc"] = (
            "no proporcionada: la distancia no se puede medir en una imagen, la aporta el usuario o un catálogo"
        )

    # --- Radio físico: solo si hay tamaño angular Y distancia reales ---
    if "offset_arcsec" in row and "distance_pc" in row:
        radius_pc = row["offset_arcsec"] / 206265.0 * row["distance_pc"]
        row["radius_pc"] = radius_pc
        if "offset_err_arcsec" in row or "distance_err_pc" in row:
            relative = 0.0
            if "offset_err_arcsec" in row and row["offset_arcsec"] > 0:
                relative += (row["offset_err_arcsec"] / row["offset_arcsec"]) ** 2
            if "distance_err_pc" in row and row["distance_pc"] > 0:
                relative += (row["distance_err_pc"] / row["distance_pc"]) ** 2
            if relative > 0:
                row["radius_err_pc"] = abs(radius_pc) * math.sqrt(relative)
    else:
        missing = "tamaño angular" if "offset_arcsec" not in row else "distancia"
        unavailable["radius_pc"] = f"no derivable sin {missing} (aproximación de ángulo pequeño: radio = ángulo x distancia)"

    # --- Velocidad: espectroscópica o de movimiento propio, nunca de una imagen ---
    if velocity_kms is not None and math.isfinite(velocity_kms) and velocity_kms > 0:
        row["velocity_kms"] = float(velocity_kms)
        if velocity_err_kms is not None and math.isfinite(velocity_err_kms) and velocity_err_kms > 0:
            row["velocity_err_kms"] = float(velocity_err_kms)
    else:
        unavailable["velocity_kms"] = (
            "no proporcionada: requiere espectroscopía (desplazamiento de línea) o movimiento propio con distancia conocida"
        )

    return PhysicalObservables(row=row, unavailable=unavailable, object_family=object_family)
