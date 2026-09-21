"""Comparación de un espectro observado con una plantilla de referencia
(§25): dos espectros 1D REALES ya calibrados en longitud de onda -- la
"plantilla" es CUALQUIER otro espectro 1D real que el usuario elija
(otra observación propia, una estrella estándar, un espectro de
referencia guardado como FITS por otro programa), nunca un catálogo
interno de tipos espectrales.

Deliberadamente NO clasifica ni sugiere un tipo espectral (§25/§26): sin
una biblioteca real de plantillas por tipo espectral de la que
generalizar, cualquier "coincidencia" automática sería una clasificación
inventada -- esto es una herramienta de comparación visual (observado,
plantilla, residuo), la decisión siempre es del usuario.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_VALID_NORMALIZATIONS = ("median", "none")
_VALID_OPERATIONS = ("subtract", "divide")


@dataclass(frozen=True)
class TemplateComparisonResult:
    wavelength: np.ndarray
    """El eje REAL del espectro observado -- nunca extrapolado ni
    resampleado; la plantilla se interpola SOBRE este eje, no al revés."""
    observed_flux: np.ndarray
    """Flujo observado, normalizado según `normalize`."""
    template_flux: np.ndarray
    """Flujo de la plantilla interpolado real sobre `wavelength` --
    `NaN` fuera del rango real cubierto por la plantilla (nunca
    extrapolado más allá de los datos reales de la plantilla)."""
    residual: np.ndarray
    """Según `operation`: `observed_flux - template_flux` (resta, por
    defecto) o `observed_flux / template_flux` (cociente) -- `NaN` donde
    `template_flux` es `NaN` (fuera del rango real de la plantilla) o,
    en el cociente, donde `template_flux` es cero (división real por
    cero, nunca infinito silencioso)."""
    operation: str
    """`"subtract"` o `"divide"` -- qué operación real produjo `residual`."""
    observed_scale: float
    template_scale: float
    overlap_fraction: float
    """Fracción de `wavelength` real cubierta por el rango real de la
    plantilla, en [0, 1] -- una comparación con solape bajo es poco
    significativa; este módulo solo lo reporta, el llamador decide
    cómo avisar."""


def compare_to_template(
    observed_wavelength: np.ndarray,
    observed_flux: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux: np.ndarray,
    *,
    normalize: str = "median",
    operation: str = "subtract",
) -> TemplateComparisonResult:
    """`normalize`: `"median"` (por defecto) reescala cada espectro por
    su propia mediana real sobre la región de solape real -- para poder
    comparar la FORMA aunque los dos espectros tengan niveles de flujo
    absolutos distintos (p. ej. uno en ADU y otro ya calibrado en
    unidades físicas); `"none"` compara los valores tal cual, útil
    cuando los dos YA están en las mismas unidades físicas reales
    (p. ej. dos espectros calibrados en flujo con `fluxcal.calibrate_
    flux`).

    `operation`: `"subtract"` (por defecto, `observado - plantilla`) o
    `"divide"` (`observado / plantilla`, real división real por real --
    NaN donde la plantilla vale cero, nunca infinito silencioso).

    Lanza `ValueError` (nunca un resultado silenciosamente vacío) si la
    plantilla no solapa en absoluto con el espectro observado."""
    if normalize not in _VALID_NORMALIZATIONS:
        raise ValueError(f"normalize debe ser uno de {_VALID_NORMALIZATIONS}, recibido {normalize!r}")
    if operation not in _VALID_OPERATIONS:
        raise ValueError(f"operation debe ser una de {_VALID_OPERATIONS}, recibida {operation!r}")

    observed_wavelength = np.asarray(observed_wavelength, dtype=np.float64)
    observed_flux = np.asarray(observed_flux, dtype=np.float64)
    template_wavelength = np.asarray(template_wavelength, dtype=np.float64)
    template_flux = np.asarray(template_flux, dtype=np.float64)
    if observed_wavelength.shape != observed_flux.shape:
        raise ValueError("observed_wavelength y observed_flux deben tener la misma forma")
    if template_wavelength.shape != template_flux.shape:
        raise ValueError("template_wavelength y template_flux deben tener la misma forma")
    if template_wavelength.size < 2:
        raise ValueError("la plantilla necesita al menos dos puntos reales para poder interpolarse")

    order = np.argsort(template_wavelength)
    template_wavelength_sorted = template_wavelength[order]
    template_flux_sorted = template_flux[order]

    in_range = (observed_wavelength >= template_wavelength_sorted[0]) & (observed_wavelength <= template_wavelength_sorted[-1])
    if not np.any(in_range):
        raise ValueError(
            f"la plantilla ({template_wavelength_sorted[0]:.1f}-{template_wavelength_sorted[-1]:.1f} Å) no solapa en "
            f"absoluto con el espectro observado ({observed_wavelength.min():.1f}-{observed_wavelength.max():.1f} Å)"
        )
    overlap_fraction = float(np.count_nonzero(in_range) / observed_wavelength.size) if observed_wavelength.size else 0.0

    template_on_observed_grid = np.interp(
        observed_wavelength, template_wavelength_sorted, template_flux_sorted, left=np.nan, right=np.nan,
    )

    if normalize == "median":
        observed_scale = float(np.nanmedian(observed_flux[in_range])) or 1.0
        template_scale = float(np.nanmedian(template_on_observed_grid[in_range])) or 1.0
    else:
        observed_scale = 1.0
        template_scale = 1.0

    observed_normalized = observed_flux / observed_scale
    template_normalized = template_on_observed_grid / template_scale

    if operation == "subtract":
        result_value = observed_normalized - template_normalized
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            result_value = np.where(template_normalized != 0.0, observed_normalized / template_normalized, np.nan)

    return TemplateComparisonResult(
        wavelength=observed_wavelength,
        observed_flux=observed_normalized,
        template_flux=template_normalized,
        residual=result_value,
        operation=operation,
        observed_scale=observed_scale,
        template_scale=template_scale,
        overlap_fraction=overlap_fraction,
    )
