"""`Quantity`: el bloque atómico reutilizado por todos los motores para
representar "un valor con su incertidumbre y su procedencia epistémica".

Se usa para flujo, S/N, FWHM, ratios de líneas, velocidad de choque,
anomalías individuales del AnomalyVector, etc. -- en vez de que cada
motor reinvente su propia mezcla de campos `*_err`/`*_state`/`*_method`
(el patrón que ya existía, disperso, en el código heredado; ver
docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md, seccion 5.4).
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from astrophysics_suite.core.enums import ValueKind


@dataclass(frozen=True)
class Quantity:
    """Un valor físico/estadístico con su incertidumbre y procedencia.

    Invariantes exigidas en `__post_init__`:
      - si `kind` es NOT_AVAILABLE, `value` debe ser None (no se permite un
        número "disponible" bajo un estado que dice que no lo está);
      - si `kind` no es NOT_AVAILABLE, `value` debe ser un float finito
        (nunca NaN/inf silencioso: si no se puede calcular, el estado es
        NOT_AVAILABLE, no un número inválido);
      - `error`, si se da, debe ser finito y >= 0.
    """

    value: float | None
    error: float | None
    unit: str
    kind: ValueKind
    method: str
    reference: str = ""
    notes: tuple[str, ...] = ()

    def __post_init__(self):
        if self.kind == ValueKind.NOT_AVAILABLE:
            if self.value is not None:
                raise ValueError("Quantity con kind=NOT_AVAILABLE no puede llevar un value numérico")
        else:
            if self.value is None or not math.isfinite(self.value):
                raise ValueError(
                    f"Quantity con kind={self.kind} requiere un value finito; recibido {self.value!r}. "
                    "Si el valor no se puede calcular, usa kind=NOT_AVAILABLE en vez de NaN/inf."
                )
        if self.error is not None and (not math.isfinite(self.error) or self.error < 0):
            raise ValueError(f"Quantity.error debe ser finito y >= 0; recibido {self.error!r}")
        if not self.method:
            raise ValueError("Quantity.method no puede estar vacío: toda cantidad declara cómo se obtuvo")

    @classmethod
    def not_available(cls, unit: str, method: str, reference: str = "", *, notes: tuple[str, ...] = ()) -> "Quantity":
        return cls(value=None, error=None, unit=unit, kind=ValueKind.NOT_AVAILABLE, method=method, reference=reference, notes=notes)

    @property
    def is_available(self) -> bool:
        return self.kind != ValueKind.NOT_AVAILABLE

    def to_dict(self) -> dict[str, Any]:
        return {
            "value": self.value,
            "error": self.error,
            "unit": self.unit,
            "kind": self.kind.value,
            "method": self.method,
            "reference": self.reference,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Quantity":
        return cls(
            value=data.get("value"),
            error=data.get("error"),
            unit=data.get("unit", ""),
            kind=ValueKind(data["kind"]),
            method=data.get("method", ""),
            reference=data.get("reference", ""),
            notes=tuple(data.get("notes", ()) or ()),
        )
