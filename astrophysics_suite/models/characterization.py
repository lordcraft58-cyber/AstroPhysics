"""`CharacterizationResult`: lo que el Characterization Engine mide sobre
una Detection ya pasada por el Artifact Rejection Engine.

Cubre tanto fuentes puntuales (FWHM, elipticidad, flujo, color,
movimiento propio, variabilidad) como extendidas (área, tamaño angular,
brillo superficial, estructura filamentaria, ratios Hα/[O III]) sin forzar
un esquema único: los campos comunes son explícitos y tipados; lo
específico de cada familia de objeto vive en `extra`, con el mismo tipo
`Quantity` que todo lo demás -- nunca un float suelto sin procedencia.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.detection import SkyPosition

SCHEMA_VERSION = 1


def _quantity_dict_to_dict(d: dict[str, Quantity]) -> dict[str, Any]:
    return {k: v.to_dict() for k, v in d.items()}


def _quantity_dict_from_dict(d: dict[str, Any]) -> dict[str, Quantity]:
    return {k: Quantity.from_dict(v) for k, v in d.items()}


@dataclass(frozen=True)
class CharacterizationResult:
    schema_version: int
    detection_id: str
    position: SkyPosition
    """Posición refinada (puede diferir ligeramente de la del Detection
    original tras el ajuste de perfil/centroide)."""
    size: Quantity | None = None
    area: Quantity | None = None
    elongation: Quantity | None = None
    fwhm: Quantity | None = None
    surface_brightness: Quantity | None = None
    band_flux: dict[str, Quantity] = field(default_factory=dict)
    band_ratios: dict[str, Quantity] = field(default_factory=dict)
    color: dict[str, Quantity] = field(default_factory=dict)
    proper_motion: Quantity | None = None
    variability: Quantity | None = None
    extra: dict[str, Quantity] = field(default_factory=dict)
    """Mediciones específicas de familia de objeto (p. ej.
    "filament_length_arcsec", "filament_curvature") que no tienen sitio
    en los campos comunes de arriba."""
    provenance: Provenance | None = None

    @classmethod
    def create(cls, *, detection_id: str, position: SkyPosition, provenance: Provenance | None = None, **kwargs) -> "CharacterizationResult":
        return cls(schema_version=SCHEMA_VERSION, detection_id=detection_id, position=position, provenance=provenance, **kwargs)

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema_version": self.schema_version,
            "detection_id": self.detection_id,
            "position": self.position.to_dict(),
            "size": self.size.to_dict() if self.size else None,
            "area": self.area.to_dict() if self.area else None,
            "elongation": self.elongation.to_dict() if self.elongation else None,
            "fwhm": self.fwhm.to_dict() if self.fwhm else None,
            "surface_brightness": self.surface_brightness.to_dict() if self.surface_brightness else None,
            "band_flux": _quantity_dict_to_dict(self.band_flux),
            "band_ratios": _quantity_dict_to_dict(self.band_ratios),
            "color": _quantity_dict_to_dict(self.color),
            "proper_motion": self.proper_motion.to_dict() if self.proper_motion else None,
            "variability": self.variability.to_dict() if self.variability else None,
            "extra": _quantity_dict_to_dict(self.extra),
            "provenance": self.provenance.to_dict() if self.provenance else None,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "CharacterizationResult":
        def q(key: str) -> Quantity | None:
            return Quantity.from_dict(data[key]) if data.get(key) else None

        return cls(
            schema_version=data.get("schema_version", SCHEMA_VERSION),
            detection_id=data["detection_id"],
            position=SkyPosition.from_dict(data["position"]),
            size=q("size"),
            area=q("area"),
            elongation=q("elongation"),
            fwhm=q("fwhm"),
            surface_brightness=q("surface_brightness"),
            band_flux=_quantity_dict_from_dict(data.get("band_flux", {})),
            band_ratios=_quantity_dict_from_dict(data.get("band_ratios", {})),
            color=_quantity_dict_from_dict(data.get("color", {})),
            proper_motion=q("proper_motion"),
            variability=q("variability"),
            extra=_quantity_dict_from_dict(data.get("extra", {})),
            provenance=Provenance.from_dict(data["provenance"]) if data.get("provenance") else None,
        )
