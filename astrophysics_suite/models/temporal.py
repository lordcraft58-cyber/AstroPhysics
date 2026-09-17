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
from datetime import datetime
from typing import Any

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity

SCHEMA_VERSION = 1


def _q(v: Quantity | None) -> Any:
    return v.to_dict() if v else None


def _qf(data: dict[str, Any], key: str) -> Quantity | None:
    return Quantity.from_dict(data[key]) if data.get(key) else None


@dataclass(frozen=True)
class TemporalEpoch:
    """Un punto real de la serie temporal que alimentó `analyze_
    variability` -- sin esto, `reporting/` no tiene con qué dibujar una
    curva de luz real: `TemporalEvidence` por sí sola solo lleva el
    AJUSTE (pendiente, significancia), no los puntos medidos.

    `time` es el mismo valor numérico (horas desde la primera época,
    normalmente -- ver `discovery/pipeline.py::_brightness_epochs`) que
    ya recibe `analyze_variability`, no una fecha absoluta: ese motor
    nunca ha requerido un `DATE-OBS` real, solo un eje temporal relativo
    consistente entre épocas."""

    time: float
    value: float
    error: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time, "value": self.value, "error": self.error}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemporalEpoch":
        return cls(time=data["time"], value=data["value"], error=data.get("error"))


@dataclass(frozen=True)
class MotionEpoch:
    """Un punto real (época, RA, Dec) de la trayectoria que ajustó
    `analyze_motion` -- mismo motivo que `TemporalEpoch`: `MotionEvidence`
    por sí sola solo lleva el resultado del ajuste lineal, no los puntos."""

    time: datetime
    ra_deg: float
    dec_deg: float

    def to_dict(self) -> dict[str, Any]:
        return {"time": self.time.isoformat(), "ra_deg": self.ra_deg, "dec_deg": self.dec_deg}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotionEpoch":
        return cls(time=datetime.fromisoformat(data["time"]), ra_deg=data["ra_deg"], dec_deg=data["dec_deg"])


@dataclass(frozen=True)
class TemporalEvidence:
    schema_version: int
    detection_id: str
    n_epochs: int
    provenance: Provenance
    appearance_detected: bool = False
    disappearance_detected: bool = False
    brightness_change: Quantity | None = None
    morphology_change: Quantity | None = None
    color_change: Quantity | None = None
    variable_candidate: bool = False
    notes: tuple[str, ...] = ()
    epochs: tuple[TemporalEpoch, ...] = ()

    @classmethod
    def create(cls, *, detection_id: str, n_epochs: int, provenance: Provenance, **kwargs) -> "TemporalEvidence":
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, n_epochs=n_epochs, provenance=provenance, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "n_epochs": self.n_epochs,
            "provenance": self.provenance.to_dict(),
            "appearance_detected": self.appearance_detected,
            "disappearance_detected": self.disappearance_detected,
            "brightness_change": _q(self.brightness_change),
            "morphology_change": _q(self.morphology_change),
            "color_change": _q(self.color_change),
            "variable_candidate": self.variable_candidate,
            "notes": list(self.notes),
            "epochs": [e.to_dict() for e in self.epochs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TemporalEvidence":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            n_epochs=data["n_epochs"],
            provenance=Provenance.from_dict(data["provenance"]),
            appearance_detected=bool(data.get("appearance_detected", False)),
            disappearance_detected=bool(data.get("disappearance_detected", False)),
            brightness_change=_qf(data, "brightness_change"),
            morphology_change=_qf(data, "morphology_change"),
            color_change=_qf(data, "color_change"),
            variable_candidate=bool(data.get("variable_candidate", False)),
            notes=tuple(data.get("notes", ()) or ()),
            epochs=tuple(TemporalEpoch.from_dict(e) for e in data.get("epochs", ())),
        )


@dataclass(frozen=True)
class MotionEvidence:
    schema_version: int
    detection_id: str
    n_epochs_used: int
    provenance: Provenance
    pm_total: Quantity | None = None
    pm_ra: Quantity | None = None
    pm_dec: Quantity | None = None
    moving_source_candidate: bool = False
    epochs: tuple[MotionEpoch, ...] = ()

    @classmethod
    def create(cls, *, detection_id: str, n_epochs_used: int, provenance: Provenance, **kwargs) -> "MotionEvidence":
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, n_epochs_used=n_epochs_used, provenance=provenance, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "n_epochs_used": self.n_epochs_used,
            "provenance": self.provenance.to_dict(),
            "pm_total": _q(self.pm_total),
            "pm_ra": _q(self.pm_ra),
            "pm_dec": _q(self.pm_dec),
            "moving_source_candidate": self.moving_source_candidate,
            "epochs": [e.to_dict() for e in self.epochs],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MotionEvidence":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            n_epochs_used=data["n_epochs_used"],
            provenance=Provenance.from_dict(data["provenance"]),
            pm_total=_qf(data, "pm_total"),
            pm_ra=_qf(data, "pm_ra"),
            pm_dec=_qf(data, "pm_dec"),
            moving_source_candidate=bool(data.get("moving_source_candidate", False)),
            epochs=tuple(MotionEpoch.from_dict(e) for e in data.get("epochs", ())),
        )
