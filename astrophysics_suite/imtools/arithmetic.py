"""Aritmética de imágenes con propagación rigurosa de incertidumbre --
equivalente propio de `imarith`/`imcombine` de IRAF en la parte de
incertidumbre (IRAF clásico no propagaba varianza; esto es una mejora
deliberada, no una réplica literal).

`UncertainImage` empareja un array de datos con su array de incertidumbre
1-sigma (misma forma, mismas unidades) y una máscara opcional de píxeles
inválidos. Las incertidumbres de entrada se derivan del modelo de ruido
CCD estándar -- Poisson de la señal (fuente + corriente de oscuridad) más
ruido de lectura gaussiano, ver Howell, *Handbook of CCD Astronomy* -- y
se propagan a través de +, -, *, / mediante las reglas estándar de
propagación de errores de primer orden (independencia estadística entre
operandos; válido mientras las incertidumbres sean pequeñas frente a la
señal, la misma suposición que usa cualquier pipeline de reducción).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class UncertainImage:
    data: np.ndarray
    uncertainty: np.ndarray
    """1-sigma, misma forma y unidad que `data`. Nunca negativa."""
    unit: str = "adu"
    mask: np.ndarray | None = None
    """`True` = píxel inválido (saturado, rechazado, fuera del área útil
    tras un recorte). Las operaciones aritméticas combinan máscaras con
    OR lógico: un píxel inválido en cualquier operando lo es en el
    resultado."""

    def __post_init__(self) -> None:
        if self.data.shape != self.uncertainty.shape:
            raise ValueError(
                f"data y uncertainty deben tener la misma forma; recibido {self.data.shape} vs {self.uncertainty.shape}"
            )
        if self.mask is not None and self.mask.shape != self.data.shape:
            raise ValueError(f"mask debe tener la misma forma que data; recibido {self.mask.shape} vs {self.data.shape}")
        finite_uncertainty = self.uncertainty[np.isfinite(self.uncertainty)]
        if finite_uncertainty.size and np.any(finite_uncertainty < 0):
            raise ValueError("uncertainty no puede contener valores negativos")

    @property
    def shape(self) -> tuple[int, ...]:
        return self.data.shape

    @classmethod
    def from_counts(
        cls,
        data: np.ndarray,
        *,
        gain_e_per_adu: float = 1.0,
        read_noise_e: float = 0.0,
        dark_current_e_per_s: float = 0.0,
        exposure_s: float = 0.0,
        unit: str = "adu",
        mask: np.ndarray | None = None,
    ) -> "UncertainImage":
        """Deriva la incertidumbre 1-sigma de una imagen en ADU ya
        corregida de bias, a partir del modelo de ruido CCD estándar:

            sigma_e^2 = max(señal_e, 0) + ruido_lectura_e^2 + corriente_oscura_e

        (Poisson de la señal medida como proxy de la señal verdadera --
        la aproximación habitual cuando no se dispone del flujo real --
        más Poisson de la corriente de oscuridad integrada en el tiempo
        de exposición, más el ruido de lectura gaussiano de la cámara).
        El resultado se devuelve en las mismas unidades que `data` (ADU
        por defecto), dividiendo por la ganancia.
        """
        if gain_e_per_adu <= 0:
            raise ValueError("gain_e_per_adu debe ser positivo")
        signal_e = np.clip(data.astype(np.float64) * gain_e_per_adu, a_min=0.0, a_max=None)
        dark_e = max(dark_current_e_per_s, 0.0) * max(exposure_s, 0.0)
        variance_e = signal_e + read_noise_e**2 + dark_e
        uncertainty_adu = np.sqrt(variance_e) / gain_e_per_adu
        return cls(data=data.astype(np.float64), uncertainty=uncertainty_adu, unit=unit, mask=mask)

    def _combined_mask(self, other: "UncertainImage | None") -> np.ndarray | None:
        if other is None:
            return self.mask
        if self.mask is None and other.mask is None:
            return None
        self_mask = self.mask if self.mask is not None else np.zeros(self.shape, dtype=bool)
        other_mask = other.mask if other.mask is not None else np.zeros(other.shape, dtype=bool)
        return self_mask | other_mask

    def _check_compatible(self, other: "UncertainImage") -> None:
        if self.shape != other.shape:
            raise ValueError(f"formas incompatibles: {self.shape} vs {other.shape}")
        if self.unit != other.unit:
            raise ValueError(f"unidades incompatibles: {self.unit!r} vs {other.unit!r} -- convierte antes de operar")

    def __add__(self, other: "UncertainImage | float") -> "UncertainImage":
        if isinstance(other, UncertainImage):
            self._check_compatible(other)
            data = self.data + other.data
            uncertainty = np.sqrt(self.uncertainty**2 + other.uncertainty**2)
            return UncertainImage(data=data, uncertainty=uncertainty, unit=self.unit, mask=self._combined_mask(other))
        return UncertainImage(data=self.data + other, uncertainty=self.uncertainty.copy(), unit=self.unit, mask=self.mask)

    def __sub__(self, other: "UncertainImage | float") -> "UncertainImage":
        if isinstance(other, UncertainImage):
            self._check_compatible(other)
            data = self.data - other.data
            uncertainty = np.sqrt(self.uncertainty**2 + other.uncertainty**2)
            return UncertainImage(data=data, uncertainty=uncertainty, unit=self.unit, mask=self._combined_mask(other))
        return UncertainImage(data=self.data - other, uncertainty=self.uncertainty.copy(), unit=self.unit, mask=self.mask)

    def __mul__(self, other: "UncertainImage | float") -> "UncertainImage":
        if isinstance(other, UncertainImage):
            # unidades no comprobadas a propósito: multiplicar, p. ej., un flat
            # normalizado (adimensional) por una imagen en ADU es una operación
            # legítima y frecuente en reducción de CCD.
            data = self.data * other.data
            relative_variance = _safe_relative_variance(self.data, self.uncertainty) + _safe_relative_variance(
                other.data, other.uncertainty
            )
            uncertainty = np.abs(data) * np.sqrt(relative_variance)
            return UncertainImage(
                data=data, uncertainty=uncertainty, unit=_combine_units_multiply(self.unit, other.unit), mask=self._combined_mask(other)
            )
        data = self.data * other
        return UncertainImage(data=data, uncertainty=np.abs(self.uncertainty * other), unit=self.unit, mask=self.mask)

    def __truediv__(self, other: "UncertainImage | float") -> "UncertainImage":
        if isinstance(other, UncertainImage):
            with np.errstate(divide="ignore", invalid="ignore"):
                data = self.data / other.data
            relative_variance = _safe_relative_variance(self.data, self.uncertainty) + _safe_relative_variance(
                other.data, other.uncertainty
            )
            uncertainty = np.abs(data) * np.sqrt(relative_variance)
            division_mask = ~np.isfinite(data)
            combined = self._combined_mask(other)
            combined = division_mask if combined is None else (combined | division_mask)
            return UncertainImage(
                data=data, uncertainty=uncertainty, unit=_combine_units_divide(self.unit, other.unit), mask=combined
            )
        if other == 0:
            raise ZeroDivisionError("división por escalar cero")
        return UncertainImage(data=self.data / other, uncertainty=np.abs(self.uncertainty / other), unit=self.unit, mask=self.mask)

    def __neg__(self) -> "UncertainImage":
        return UncertainImage(data=-self.data, uncertainty=self.uncertainty.copy(), unit=self.unit, mask=self.mask)

    def snr(self) -> np.ndarray:
        """Relación señal/ruido por píxel; `inf` donde la incertidumbre es
        cero, `nan` donde tanto la señal como la incertidumbre son cero."""
        with np.errstate(divide="ignore", invalid="ignore"):
            return np.where(self.uncertainty > 0, self.data / self.uncertainty, np.where(self.data == 0, np.nan, np.inf))


_DIMENSIONLESS_UNITS = ("dimensionless", "")


def _combine_units_multiply(unit_a: str, unit_b: str) -> str:
    if unit_b in _DIMENSIONLESS_UNITS:
        return unit_a
    if unit_a in _DIMENSIONLESS_UNITS:
        return unit_b
    return f"{unit_a}*{unit_b}"


def _combine_units_divide(unit_a: str, unit_b: str) -> str:
    if unit_b in _DIMENSIONLESS_UNITS:
        return unit_a
    if unit_a == unit_b:
        return "dimensionless"
    return f"{unit_a}/{unit_b}"


def _safe_relative_variance(data: np.ndarray, uncertainty: np.ndarray) -> np.ndarray:
    """(sigma/x)^2 con el convenio de que un valor central en cero (donde
    el error relativo no está definido) no propaga `inf`/`nan` en cascada
    -- se trata como error relativo cero, dejando que la incertidumbre
    absoluta del otro operando siga dominando el resultado."""
    with np.errstate(divide="ignore", invalid="ignore"):
        relative = np.where(data != 0, (uncertainty / data) ** 2, 0.0)
    return relative
