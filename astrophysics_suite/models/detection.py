"""`Detection`: lo que produce el Detection Engine antes de cualquier
rechazo de artefactos, identificación o caracterización física -- solo
"aquí hay algo, con esta forma cruda y esta posición".
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.core.provenance import Provenance

SCHEMA_VERSION = 1


@dataclass(frozen=True)
class SkyPosition:
    x_px: float
    y_px: float
    ra_deg: float | None = None
    dec_deg: float | None = None
    position_error_arcsec: float | None = None

    def __post_init__(self):
        has_ra = self.ra_deg is not None
        has_dec = self.dec_deg is not None
        if has_ra != has_dec:
            raise ValueError("SkyPosition: ra_deg y dec_deg deben darse juntos o ninguno (WCS parcial no es válido)")

    @property
    def has_sky_coordinates(self) -> bool:
        return self.ra_deg is not None

    def to_dict(self) -> dict[str, Any]:
        return {
            "x_px": self.x_px,
            "y_px": self.y_px,
            "ra_deg": self.ra_deg,
            "dec_deg": self.dec_deg,
            "position_error_arcsec": self.position_error_arcsec,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SkyPosition":
        return cls(
            x_px=data["x_px"],
            y_px=data["y_px"],
            ra_deg=data.get("ra_deg"),
            dec_deg=data.get("dec_deg"),
            position_error_arcsec=data.get("position_error_arcsec"),
        )


@dataclass(frozen=True)
class MorphologySummary:
    morphology_class: MorphologyClass
    area_px: float
    elongation: float
    compactness: float
    fwhm_px: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "morphology_class": self.morphology_class.value,
            "area_px": self.area_px,
            "elongation": self.elongation,
            "compactness": self.compactness,
            "fwhm_px": self.fwhm_px,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "MorphologySummary":
        return cls(
            morphology_class=MorphologyClass(data["morphology_class"]),
            area_px=data["area_px"],
            elongation=data["elongation"],
            compactness=data["compactness"],
            fwhm_px=data.get("fwhm_px"),
        )


@dataclass(frozen=True)
class Detection:
    schema_version: int
    detection_id: str
    observation_id: str
    position: SkyPosition
    morphology: MorphologySummary
    bands: tuple[str, ...]
    peak_snr: float
    method: str
    """Método de detección usado -- p. ej. "DAOStarFinder", "connected_components_snr", "hessian_filament"."""
    provenance: Provenance

    @classmethod
    def create(
        cls,
        *,
        detection_id: str,
        observation_id: str,
        position: SkyPosition,
        morphology: MorphologySummary,
        bands: tuple[str, ...],
        peak_snr: float,
        method: str,
        provenance: Provenance,
    ) -> "Detection":
        return cls(
            schema_version=SCHEMA_VERSION,
            detection_id=detection_id,
            observation_id=observation_id,
            position=position,
            morphology=morphology,
            bands=bands,
            peak_snr=peak_snr,
            method=method,
            provenance=provenance,
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "observation_id": self.observation_id,
            "position": self.position.to_dict(),
            "morphology": self.morphology.to_dict(),
            "bands": list(self.bands),
            "peak_snr": self.peak_snr,
            "method": self.method,
            "provenance": self.provenance.to_dict(),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "Detection":
        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            observation_id=data["observation_id"],
            position=SkyPosition.from_dict(data["position"]),
            morphology=MorphologySummary.from_dict(data["morphology"]),
            bands=tuple(data.get("bands", ())),
            peak_snr=data["peak_snr"],
            method=data["method"],
            provenance=Provenance.from_dict(data["provenance"]),
        )
