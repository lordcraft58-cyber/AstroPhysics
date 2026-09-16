"""Carga imágenes reales y construye `Observation`/`ImageRef` (Fase 4)
a partir de ellas.

Dependencia transicional documentada: usa `load_fits`/`sha256_file` de
`legacy.AstroPhysicsSuite_v57_3_COMMERCIAL` -- ya probados (manejo de
cubos 3D/4D sin selección silenciosa de plano, WCS, memmap) -- en vez de
reescribir la lectura de FITS desde cero. `LoadedImage.legacy_image`
expone el objeto `FitsImage` heredado para que otros motores en
migración (p. ej. `detection/point_sources.py`) puedan operar sobre los
píxeles reales sin releer el archivo ni duplicar la lógica de lectura.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import load_fits, sha256_file

from astrophysics_suite.models.observation import ImageRef, Observation


@dataclass(frozen=True)
class LoadedImage:
    image_ref: ImageRef
    legacy_image: Any
    """El `FitsImage` heredado -- `.data`, `.header`, `.wcs`,
    `.pixel_to_world(x, y)`. Ver el aviso de dependencia transicional
    arriba: motores nuevos pueden consumir esto mientras se migran, pero
    no debe filtrarse a `models/` ni a ningún contrato de la Fase 4."""


def load_image(path: str, *, band: str, role: str = "science") -> LoadedImage:
    """Carga un FITS real y construye su `ImageRef` tipado.

    Lanza lo mismo que `load_fits` (incluida `AmbiguousCubeError` para
    cubos 3D/4D sin plano explícito) -- este wrapper no oculta esos
    errores ni decide por el llamador.
    """
    legacy_image = load_fits(path)
    image_ref = ImageRef(
        path=str(Path(path).resolve()),
        band=band,
        role=role,
        pixel_scale_arcsec=legacy_image.pixel_scale_arcsec,
        has_wcs=legacy_image.wcs is not None,
        sha256=sha256_file(Path(path)),
    )
    return LoadedImage(image_ref=image_ref, legacy_image=legacy_image)


def build_observation(
    images: list[tuple[str, str]],
    *,
    observation_id: str,
    target_name: str,
    created_at: datetime | None = None,
    epoch: datetime | None = None,
    instrument: str = "",
    notes: str = "",
    role: str = "science",
) -> tuple[Observation, dict[str, LoadedImage]]:
    """Construye una `Observation` real a partir de una lista de (path, band).

    Devuelve también un `dict[path, LoadedImage]` para que el resto del
    pipeline (Fase 6 en adelante) no tenga que volver a tocar disco --
    cada motor recibe los píxeles ya cargados, no una ruta que releer.
    """
    loaded = {path: load_image(path, band=band, role=role) for path, band in images}
    observation = Observation.create(
        observation_id=observation_id,
        target_name=target_name,
        created_at=created_at or datetime.now(timezone.utc),
        images=tuple(li.image_ref for li in loaded.values()),
        epoch=epoch,
        instrument=instrument,
        notes=notes,
    )
    return observation, loaded
