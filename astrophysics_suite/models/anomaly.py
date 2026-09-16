"""`AnomalyVector`: NO es un score único opaco. Es un conjunto de
evidencias de anomalía separadas -- fotométrica, morfológica, espectral,
temporal, astrométrica, espacial y física -- cada una con su propio valor,
incertidumbre, método y referencia (`Quantity`), tal como pide el
encargo original explícitamente ("no quiero un único puntaje opaco").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astrophysics_suite.core.quantity import Quantity

SCHEMA_VERSION = 1

_DIMENSIONS = (
    "photometric",
    "morphological",
    "spectral",
    "temporal",
    "astrometric",
    "spatial",
    "physical",
)


@dataclass(frozen=True)
class AnomalyVector:
    schema_version: int
    detection_id: str
    photometric: Quantity | None = None
    morphological: Quantity | None = None
    spectral: Quantity | None = None
    temporal: Quantity | None = None
    astrometric: Quantity | None = None
    spatial: Quantity | None = None
    physical: Quantity | None = None

    @classmethod
    def create(cls, *, detection_id: str, **dimensions: Quantity | None) -> "AnomalyVector":
        unknown = set(dimensions) - set(_DIMENSIONS)
        if unknown:
            raise ValueError(f"Dimensiones de anomalía desconocidas: {sorted(unknown)}")
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, **dimensions)

    @property
    def flagged_dimensions(self) -> tuple[str, ...]:
        """Dimensiones con evidencia de anomalía disponible (no
        NOT_AVAILABLE) -- no implica por sí solo que la anomalía sea
        significativa; el umbral de significancia es responsabilidad del
        Anomaly Engine que produjo cada Quantity, no de este contenedor."""
        return tuple(name for name in _DIMENSIONS if (q := getattr(self, name)) is not None and q.is_available)

    @property
    def independent_evidence_count(self) -> int:
        return len(self.flagged_dimensions)

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {"schema_version": self.schema_version, "detection_id": self.detection_id}
        for name in _DIMENSIONS:
            q = getattr(self, name)
            out[name] = q.to_dict() if q else None
        return out

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "AnomalyVector":
        kwargs = {name: (Quantity.from_dict(data[name]) if data.get(name) else None) for name in _DIMENSIONS}
        return cls(schema_version=data.get("schema_version", SCHEMA_VERSION), detection_id=data["detection_id"], **kwargs)
