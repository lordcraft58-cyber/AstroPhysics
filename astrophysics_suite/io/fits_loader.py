"""Carga imágenes reales y construye `Observation`/`ImageRef` (Fase 4)
a partir de ellas.

La lectura de FITS vive ahora en `astrophysics_suite/io/fits_reader.py`
(migrada del monolito legacy, con prueba de regresión que compara los
dos lectores campo a campo sobre archivos reales). Hasta ese motor, este
módulo importaba `load_fits`/`sha256_file` de
`legacy.AstroPhysicsSuite_v57_3_COMMERCIAL` como "dependencia
transicional" -- ya no.

Soporte XISF (formato nativo de PixInsight, ver
`astrophysics_suite.io.xisf_reader` -- lector propio, nunca envuelve la
librería GPLv3 de PyPI): un XISF se decodifica con ese lector y entra
por `fits_image_from_arrays`, el MISMO motor de cubos/WCS/escala que un
FITS, **sin pasar por ningún archivo temporal**. La versión anterior
volcaba cada XISF a un FITS temporal en disco solo para poder
releerlo -- lo que además descartaba en silencio las claves de cabecera
no representables como tarjeta FITS. Ahora la cabecera devuelta conserva
todas las claves del XISF original."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from astrophysics_suite.io.fits_reader import (
    AmbiguousCubeError,
    FitsImage,
    fits_image_from_arrays,
    load_fits,
    sha256_file,
)
from astrophysics_suite.io.fits_reader import probe_fits_shape as _probe_fits_shape
from astrophysics_suite.io.xisf_reader import is_xisf_path, probe_xisf_shape, read_xisf_image
from astrophysics_suite.models.observation import ImageRef, Observation

__all__ = ["AmbiguousCubeError", "FitsImage", "LoadedImage", "build_observation", "load_image", "probe_fits_shape"]


@dataclass(frozen=True)
class LoadedImage:
    image_ref: ImageRef
    legacy_image: Any
    """La `FitsImage` cargada -- `.data`, `.header`, `.wcs`,
    `.pixel_to_world(x, y)`. El nombre del campo se conserva por
    compatibilidad con los motores que ya lo consumen, pero el tipo ya no
    viene del monolito: es `io.fits_reader.FitsImage`."""


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

    Un `.xisf` real (formato nativo de PixInsight, detectado por
    extensión o por la firma real del archivo, nunca solo por el nombre)
    se decodifica con el lector propio (`xisf_reader`) y entra por el
    mismo motor de cubos/WCS/escala, sin archivos temporales y sin
    perder claves de cabecera. `ImageRef.sha256` hashea siempre el
    archivo real del usuario.
    """
    if is_xisf_path(path):
        data, header = read_xisf_image(str(path))
        legacy_image = fits_image_from_arrays(str(path), data, header, plane=plane)
    else:
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
    if is_xisf_path(path):
        return probe_xisf_shape(str(path))
    return _probe_fits_shape(path, hdu=hdu)


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
