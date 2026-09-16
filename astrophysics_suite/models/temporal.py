"""Evidencia temporal y de movimiento -- lo que el Temporal Engine produce
al comparar una Detection a través de varias épocas.

Son registros de evidencia (valores medidos con su incertidumbre), no
enums de estado: el estado operativo final de un Candidate (¿es
TRANSIENT_CANDIDATE? ¿MOVING_SOURCE_CANDIDATE?) lo decide la orquestación
del Discovery Engine combinando esta evidencia con la del resto de
motores -- nunca esta evidencia por sí sola (ver
docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 8.1: no se debe mezclar
el vocabulario de identificación con las señales que lo alimentan).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrophysics_suite.core.quantity import Quantity

SCHEMA_VERSION = 1


def _q(v: Quantity | None) -> Any:
    return v.to_dict() if v else None


def _qf(data: dict[str, Any], key: str) -> Quantity | None:
    return Quantity.from_dict(data[key]) if data.get(key) else None


@dataclass(frozen=True)
class TemporalEvidence:
    schema_version: int
    detection_id: str
    n_epochs: int
    appearance_detected: bool = False
    disappearance_detected: bool = False
    brightness_change: Quantity | None = None
    morphology_change: Quantity | None = None
    color_change: Quantity | None = None
    variable_candidate: bool = False
    notes: tuple[str, ...] = ()

    @classmethod
    def create(cls, *, detection_id: str, n_epochs: int, **kwargs) -> "TemporalEvidence":
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, n_epochs=n_epochs, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "n_epochs": self.n_epochs,
            "appearance_detected": self.appearance_detected,
            "disappearance_detected": self.disappearance_detected,
            "brightness_change": _q(self.brightness_change),
            "morphology_change": _q(self.morphology_change),
            "color_change": _q(self.color_change),
            "variable_candidate": self.variable_candidate,
            "notes": list(self.notes),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemporalEvidence":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            n_epochs=data["n_epochs"],
            appearance_detected=bool(data.get("appearance_detected", False)),
            disappearance_detected=bool(data.get("disappearance_detected", False)),
            brightness_change=_qf(data, "brightness_change"),
            morphology_change=_qf(data, "morphology_change"),
            color_change=_qf(data, "color_change"),
            variable_candidate=bool(data.get("variable_candidate", False)),
            notes=tuple(data.get("notes", ()) or ()),
        )


@dataclass(frozen=True)
class MotionEvidence:
    schema_version: int
    detection_id: str
    n_epochs_used: int
    pm_total: Quantity | None = None
    pm_ra: Quantity | None = None
    pm_dec: Quantity | None = None
    moving_source_candidate: bool = False

    @classmethod
    def create(cls, *, detection_id: str, n_epochs_used: int, **kwargs) -> "MotionEvidence":
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, n_epochs_used=n_epochs_used, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "n_epochs_used": self.n_epochs_used,
            "pm_total": _q(self.pm_total),
            "pm_ra": _q(self.pm_ra),
            "pm_dec": _q(self.pm_dec),
            "moving_source_candidate": self.moving_source_candidate,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotionEvidence":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            n_epochs_used=data["n_epochs_used"],
            pm_total=_qf(data, "pm_total"),
            pm_ra=_qf(data, "pm_ra"),
            pm_dec=_qf(data, "pm_dec"),
            moving_source_candidate=bool(data.get("moving_source_candidate", False)),
        )
