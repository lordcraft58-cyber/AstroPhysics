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

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import AmbiguousCubeError, load_fits, sha256_file

from astrophysics_suite.models.observation import ImageRef, Observation

__all__ = ["AmbiguousCubeError", "LoadedImage", "build_observation", "load_image", "probe_fits_shape"]


@dataclass(frozen=True)
class LoadedImage:
    image_ref: ImageRef
    legacy_image: Any
    """El `FitsImage` heredado -- `.data`, `.header`, `.wcs`,
    `.pixel_to_world(x, y)`. Ver el aviso de dependencia transicional
    arriba: motores nuevos pueden consumir esto mientras se migran, pero
    no debe filtrarse a `models/` ni a ningún contrato de la Fase 4."""


def load_image(path: str, *, band: str, role: str = "science", plane: int | tuple[int, ...] | None = None) -> LoadedImage:
    """Carga un FITS real y construye su `ImageRef` tipado.

    Lanza lo mismo que `load_fits` (incluida `AmbiguousCubeError` para
    cubos 3D/4D sin plano explícito) -- este wrapper no oculta esos
    errores ni decide por el llamador. `plane` se pasa tal cual a
    `load_fits` -- un entero si el cubo tiene un solo eje sobrante, o una
    tupla si tiene varios (ver `AmbiguousCubeError` para el mensaje que
    indica cuántos hacen falta). La GUI (`qt_app.main_window.open_fits`)
    captura `AmbiguousCubeError` en el primer intento sin `plane`, pide el
    índice al usuario, y reintenta con `plane` explícito -- nunca elige
    un plano por su cuenta.
    """
    legacy_image = load_fits(path, plane=plane)
    image_ref = ImageRef(
        path=str(Path(path).resolve()),
        band=band,
        role=role,
        pixel_scale_arcsec=legacy_image.pixel_scale_arcsec,
        has_wcs=legacy_image.wcs is not None,
        sha256=sha256_file(Path(path)),
    )
    return LoadedImage(image_ref=image_ref, legacy_image=legacy_image)


def probe_fits_shape(path: str, *, hdu: int | None = None) -> tuple[int, ...]:
    """Forma completa (posiblemente N-dimensional) del HDU de imagen sin
    cargar los píxeles -- solo lee el header. Pensado para que la GUI
    pueda preguntar al usuario qué plano de un cubo 3D/4D quiere ver
    (`AmbiguousCubeError`) sin tener que parsear la forma del propio
    mensaje de la excepción."""
    from astropy.io import fits

    with fits.open(str(path), memmap=True, lazy_load_hdus=True) as hdul:
        idx = hdu
        if idx is None:
            for i, h in enumerate(hdul):
                if getattr(h, "is_image", False) and h.header.get("NAXIS", 0) >= 2:
                    idx = i
                    break
        if idx is None:
            raise ValueError(f"{path}: no hay HDU de imagen 2D")
        header = hdul[idx].header
        naxis = int(header["NAXIS"])
        return tuple(int(header[f"NAXIS{i}"]) for i in range(naxis, 0, -1))


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

    El diccionario se indexa por `ImageRef.path` (la ruta ya resuelta por
    `load_image` vía `Path(path).resolve()`), NUNCA por la ruta cruda que
    pasó el llamador -- las dos pueden diferir como texto aunque señalen
    al mismo archivo (una ruta relativa se vuelve absoluta; en Windows,
    `QFileDialog` devuelve rutas con `/` mientras que `Path.resolve()`
    normaliza a `\\`). `run_generic_discovery` busca cada imagen por
    `image_ref.path` -- si el diccionario se indexara por la ruta cruda,
    esa búsqueda fallaría con un `KeyError` real siempre que las dos
    formas no coincidieran carácter a carácter (bug real reportado en
    uso: "Descubrimiento falló: '<ruta>'", ver
    docs/audit/25-FIX-DISCOVERY-KEYERROR-RUTA.md).
    """
    loaded_by_resolved_path: dict[str, LoadedImage] = {}
    for path, band in images:
        loaded_image = load_image(path, band=band, role=role)
        loaded_by_resolved_path[loaded_image.image_ref.path] = loaded_image
    observation = Observation.create(
        observation_id=observation_id,
        target_name=target_name,
        created_at=created_at or datetime.now(timezone.utc),
        images=tuple(li.image_ref for li in loaded_by_resolved_path.values()),
        epoch=epoch,
        instrument=instrument,
        notes=notes,
    )
    return observation, loaded_by_resolved_path
