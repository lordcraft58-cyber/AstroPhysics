"""`PhysicalInference`: lo que el Physical Engine deriva para una
Detection ya caracterizada, cuando es científicamente justificable.

Cada parámetro es un `Quantity` con su propio `kind` -- dentro de la
misma inferencia, una distancia usada como entrada puede ser OBSERVED
mientras que la edad derivada es MODEL_INFERENCE; no hay un único
"estado" global para toda la inferencia, exactamente para evitar la
sobregeneralización que el encargo pide evitar ("no convertirán
automáticamente un ratio en una velocidad... sin un modelo válido y sin
declarar hipótesis, dominio, incertidumbre y procedencia").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class PhysicalInference:
    schema_version: int
    detection_id: str
    object_family: str
    """P. ej. "SNR", "HII", "shock_front", "unknown". Determina qué modelos
    son aplicables -- nunca se aplica un modelo fuera de su dominio declarado."""
    model_id: str
    """Identificador del modelo/grid usado (ver PhysicalModelRegistry en el
    código heredado) -- cadena vacía si no se aplicó ningún modelo."""
    model_hypotheses: tuple[str, ...]
    """Supuestos explícitos del modelo (p. ej. "spherical", "adiabatic",
    "uniform_medium") -- deben poder mostrarse al usuario, nunca quedar
    implícitos."""
    domain_valid: bool
    """Si las entradas están dentro del dominio de validez declarado del
    modelo. Si es False, `parameters` no debe presentarse como fiable."""
    parameters: dict[str, Quantity] = field(default_factory=dict)
    provenance: Provenance | None = None

    @classmethod
    def create(
        cls,
        *,
        detection_id: str,
        object_family: str,
        model_id: str = "",
        model_hypotheses: tuple[str, ...] = (),
        domain_valid: bool = False,
        parameters: dict[str, Quantity] | None = None,
        provenance: Provenance | None = None,
    ) -> "PhysicalInference":
        return cls(
            schema_version=SCHEMA_VERSION,
            detection_id=detection_id,
            object_family=object_family,
            model_id=model_id,
            model_hypotheses=model_hypotheses,
            domain_valid=domain_valid,
            parameters=dict(parameters or {}),
            provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "object_family": self.object_family,
            "model_id": self.model_id,
            "model_hypotheses": list(self.model_hypotheses),
            "domain_valid": self.domain_valid,
            "parameters": {k: v.to_dict() for k, v in self.parameters.items()},
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PhysicalInference":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            object_family=data["object_family"],
            model_id=data.get("model_id", ""),
            model_hypotheses=tuple(data.get("model_hypotheses", ())),
            domain_valid=bool(data.get("domain_valid", False)),
            parameters={k: Quantity.from_dict(v) for k, v in data.get("parameters", {}).items()},
            provenance=Provenance.from_dict(data["provenance"]) if data.get("provenance") else None,
        )
