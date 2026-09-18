"""`Observation`: el punto de entrada del pipeline -- una o varias imágenes
de un mismo objeto/campo, con su metadata cruda. Es descriptiva, no un
resultado científico: por eso sus campos son tipos simples, no `Quantity`
(`Quantity` es para lo que los motores producen a partir de una
Observation, no para lo que el usuario cargó).
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class ImageRef:
    path: str
    band: str
    """P. ej. "OIII", "HA", "NII", "SII", "BROADBAND", "L-QEF"."""
    role: str
    """P. ej. "science", "starless", "bias", "dark", "flat"."""
    pixel_scale_arcsec: float | None
    has_wcs: bool
    sha256: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "path": self.path,
            "band": self.band,
            "role": self.role,
            "pixel_scale_arcsec": self.pixel_scale_arcsec,
            "has_wcs": self.has_wcs,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "ImageRef":
        return cls(
            path=data["path"],
            band=data["band"],
            role=data["role"],
            pixel_scale_arcsec=data.get("pixel_scale_arcsec"),
            has_wcs=bool(data.get("has_wcs", False)),
            sha256=data.get("sha256", ""),
        )


@dataclass(frozen=True)
class Observation:
    schema_version: int
    observation_id: str
    target_name: str
    created_at: datetime
    images: tuple[ImageRef, ...]
    epoch: datetime | None = None
    """Instante de adquisición, para que el Temporal Engine pueda ordenar
    observaciones del mismo campo por época."""
    instrument: str = ""
    notes: str = ""

    @classmethod
    def create(
        cls,
        *,
        observation_id: str,
        target_name: str,
        created_at: datetime,
        images: tuple[ImageRef, ...],
        epoch: datetime | None = None,
        instrument: str = "",
        notes: str = "",
    ) -> "Observation":
        return cls(
            schema_version=SCHEMA_VERSION,
            observation_id=observation_id,
            target_name=target_name,
            created_at=created_at,
            images=images,
            epoch=epoch,
            instrument=instrument,
            notes=notes,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "observation_id": self.observation_id,
            "target_name": self.target_name,
            "created_at": self.created_at.isoformat(),
            "images": [im.to_dict() for im in self.images],
            "epoch": self.epoch.isoformat() if self.epoch else None,
            "instrument": self.instrument,
            "notes": self.notes,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Observation":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            observation_id=data["observation_id"],
            target_name=data["target_name"],
            created_at=datetime.fromisoformat(data["created_at"]),
            images=tuple(ImageRef.from_dict(im) for im in data.get("images", ())),
            epoch=datetime.fromisoformat(data["epoch"]) if data.get("epoch") else None,
            instrument=data.get("instrument", ""),
            notes=data.get("notes", ""),
        )
