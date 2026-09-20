"""Lectura real de FITS -- migrada del monolito
`legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py` a la arquitectura nueva.

Hasta este motor, TODA la lectura de píxeles del programa entraba por
`legacy.load_fits`: el manejo de cubos, la decisión de memmap, el WCS y
la escala de placa vivían en un archivo de 14.000 líneas que la
arquitectura nueva decía estar sustituyendo. `io/fits_loader.py` lo
documentaba como "dependencia transicional"; esto la cierra.

Se conserva EXACTAMENTE el comportamiento observable (hay una prueba de
regresión que compara los dos lectores campo a campo sobre FITS reales,
`tests/regression/test_fits_reader_matches_legacy.py`), con dos
diferencias deliberadas y declaradas:

1. **Sin el lector mínimo de respaldo para "astropy ausente".** astropy
   es dependencia dura y declarada del producto (`requirements-app.txt`)
   y todo `astrophysics_suite/` ya la importa sin condiciones; mantener
   un segundo parser de FITS a mano para un caso que no puede ocurrir
   era código muerto con riesgo real (ese parser no sabía leer cubos ni
   WCS).
2. **La escala de placa por cabecera la calcula `instruments/optics.py`**
   (`pixel_scale_from_wcs_header`), que es ahora el único sitio del
   proyecto donde vive esa lógica, en vez de una tercera copia local.
"""
from __future__ import annotations

import hashlib
import logging
import math
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits
from astropy.wcs import WCS
from astropy.wcs.utils import proj_plane_pixel_scales

from astrophysics_suite.instruments.optics import pixel_scale_from_wcs_header

LOG = logging.getLogger(__name__)

_MEMMAP_BLOCKING_KEYS = ("BZERO", "BSCALE", "BLANK")
_EXCLUDED_HEADER_KEYS = ("COMMENT", "HISTORY")


class AmbiguousCubeError(ValueError):
    """FITS con más de 2 ejes (cubo 3D/4D) sin un plano/canal explícito.

    Requisito de auditoría heredado y conservado tal cual: nunca se
    selecciona el primer plano en silencio. Un cubo mal indexado podría
    analizarse como si fuera la imagen 2D correcta sin que nada lo
    delatara, así que hay que decidir explícitamente."""


@dataclass
class FitsImage:
    path: str
    data: np.ndarray
    header: dict
    pixel_scale_arcsec: float | None
    wcs: Any = None
    bunit: str = ""
    exptime: float | None = None
    filter_name: str = ""
    hdu_index: int = 0
    wcs_source: str = ""
    original_ndim: int = 2
    original_shape: tuple = field(default_factory=tuple)
    selected_plane: tuple | None = None
    """`None` si el FITS ya era 2D; si no, los índices realmente usados."""
    cube_plane_is_explicit: bool = True
    """`False` solo si se usó `allow_first_plane` (vista rápida) -- para
    que nadie confunda un plano asumido con uno elegido."""

    @property
    def shape(self):
        return self.data.shape

    def pixel_to_world(self, x, y):
        """`(ra, dec)` reales bajo los píxeles dados -- `NaN` si esta
        imagen no tiene WCS, nunca una coordenada inventada."""
        if self.wcs is None:
            return (np.full_like(np.asarray(x, float), np.nan), np.full_like(np.asarray(y, float), np.nan))
        try:
            ra, dec = self.wcs.celestial.all_pix2world(np.asarray(x, float), np.asarray(y, float), 0)
            return np.asarray(ra, float), np.asarray(dec, float)
        except Exception:  # noqa: BLE001 -- un WCS mal formado degrada a NaN, no tumba la carga
            return (np.full_like(np.asarray(x, float), np.nan), np.full_like(np.asarray(y, float), np.nan))


def sha256_file(path, chunk: int = 1 << 20) -> str:
    """Hash real del archivo completo, leído por bloques (un light de
    tu cámara son ~18 MB; cargarlo entero en memoria para hashearlo
    sería gratuito pero innecesario)."""
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        while True:
            block = handle.read(chunk)
            if not block:
                break
            digest.update(block)
    return digest.hexdigest()


def _preserve_array_view(data) -> np.ndarray:
    """Conserva vistas/memmap y no convierte dtypes globalmente -- el
    casteo a float lo hace cada operación que lo necesite, no la carga."""
    array = np.asanyarray(data)
    if not np.issubdtype(array.dtype, np.number):
        raise TypeError(f"FITS: dtype no numérico: {array.dtype}")
    return array


def select_cube_plane(data: np.ndarray, plane) -> tuple[np.ndarray, tuple[int, ...]]:
    """Reduce un array de ndim>2 a 2D con los índices dados (un entero si
    solo sobra un eje, o una tupla si sobran varios). Nunca decide por su
    cuenta: si faltan índices es un error del llamador."""
    extra = data.ndim - 2
    if isinstance(plane, (int, np.integer)):
        if extra != 1:
            raise AmbiguousCubeError(f"El cubo {data.shape} requiere {extra} índices; proporcione una tupla explícita.")
        indices = (int(plane),)
    else:
        indices = tuple(int(p) for p in plane)
    if len(indices) != extra:
        raise AmbiguousCubeError(
            f"Se requieren {extra} índice(s) de plano para un cubo de forma {data.shape}; se recibieron {len(indices)}."
        )
    out = data
    for axis, index in enumerate(indices):
        if index < 0 or index >= out.shape[0]:
            raise AmbiguousCubeError(f"Índice de plano {index} fuera de rango para el eje extra {axis} de forma {data.shape}")
        out = out[index]
    return out, indices


def _should_disable_memmap(path: str) -> bool:
    """astropy no puede mapear en memoria un HDU cuyo header declara
    `BZERO`/`BSCALE`/`BLANK` -- y así es justo como casi cualquier cámara
    CMOS de 16 bits guarda datos sin signo (la tuya incluida). astropy lo
    descubre al acceder a `.data`, no al abrir, así que se comprueba
    antes para no fallar a mitad de una carga real."""
    try:
        with fits.open(path, memmap=False, lazy_load_hdus=True) as probe:
            return any(any(key in hdu.header for key in _MEMMAP_BLOCKING_KEYS) for hdu in probe)
    except OSError:
        return False


def _first_image_hdu_index(hdul) -> int | None:
    for index, hdu in enumerate(hdul):
        if getattr(hdu, "is_image", False) and hdu.header.get("NAXIS", 0) >= 2:
            return index
    return None


def _as_fits_header(header_mapping: dict) -> fits.Header:
    """Cabecera de astropy EN MEMORIA a partir de un dict -- para poder
    derivar el WCS de una imagen que no viene de un archivo FITS (p. ej.
    un XISF). Las claves que no son representables como tarjeta FITS se
    omiten SOLO aquí, para el parseo del WCS: el dict original que se
    devuelve al llamador las conserva todas."""
    header = fits.Header()
    for key, value in header_mapping.items():
        try:
            header[key] = value
        except (ValueError, KeyError):
            continue
    return header


def _wcs_and_scale(header) -> tuple[Any, float | None, str]:
    try:
        wcs = WCS(header, naxis=2)
        if wcs.has_celestial:
            scale = float(np.mean(np.abs(proj_plane_pixel_scales(wcs.celestial))) * 3600.0)
            return wcs, scale, "WCS del propio FITS"
    except (ValueError, TypeError, AttributeError) as exc:
        LOG.debug("WCS no disponible: %s", exc)
    return None, None, ""


def _finite_or_none(value) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def load_fits(path, hdu: int | None = None, memmap: bool = True, plane=None, allow_first_plane: bool = False) -> FitsImage:
    """Carga un FITS y devuelve una imagen 2D real.

    Si el HDU elegido tiene más de 2 ejes (cubo 3D/4D):
      - `plane` explícito (int o tupla) -> se usa ese plano y queda
        registrado en el resultado;
      - `plane=None` con `allow_first_plane=True` -> plano 0, marcado
        como NO explícito (solo para vistas rápidas, nunca para ciencia);
      - `plane=None` por defecto -> `AmbiguousCubeError` con la forma
        real del cubo en el mensaje, para que el llamador pregunte.
    """
    path = str(path)
    if memmap and _should_disable_memmap(path):
        memmap = False

    with fits.open(path, memmap=memmap, lazy_load_hdus=True) as hdul:
        index = hdu if hdu is not None else _first_image_hdu_index(hdul)
        if index is None:
            raise ValueError(f"{path}: no hay HDU de imagen 2D")

        image_hdu = hdul[index]
        raw = _preserve_array_view(image_hdu.data)
        original_ndim, original_shape = raw.ndim, tuple(raw.shape)
        selected_plane: tuple[int, ...] | None = None
        explicit = True

        if raw.ndim > 2:
            if plane is not None:
                data, selected_plane = select_cube_plane(raw, plane)
            elif allow_first_plane:
                data, selected_plane = select_cube_plane(raw, 0)
                explicit = False
                LOG.warning(
                    "%s: cubo %s sin plano explícito; usando plano 0 (SOLO vista rápida, no válido para análisis científico)",
                    path, original_shape,
                )
            else:
                raise AmbiguousCubeError(
                    f"{path}: el HDU {index} tiene forma {original_shape} (ndim={raw.ndim}), no es una imagen 2D. "
                    f"Indica explícitamente el plano/canal a usar en vez de asumir el primero por defecto."
                )
        else:
            data = raw

        data = _preserve_array_view(data)
        header = {k: image_hdu.header[k] for k in image_hdu.header.keys() if k and k not in _EXCLUDED_HEADER_KEYS}
        wcs, scale, source = _wcs_and_scale(image_hdu.header)
        if scale is None:
            scale = pixel_scale_from_wcs_header(header)
            if scale:
                source = "CDELT/PIXSCALE del propio FITS"

    if data.ndim != 2:
        raise AmbiguousCubeError(
            f"{path}: tras seleccionar plano, la forma sigue siendo {data.shape} (se requiere estrictamente 2D)."
        )

    return FitsImage(
        path=path,
        data=data,
        header=header,
        pixel_scale_arcsec=scale,
        wcs=wcs,
        bunit=str(header.get("BUNIT", "")),
        exptime=_finite_or_none(header["EXPTIME"]) if "EXPTIME" in header else None,
        filter_name=str(header.get("FILTER", header.get("FILTER1", ""))),
        hdu_index=int(index),
        wcs_source=source,
        original_ndim=original_ndim,
        original_shape=original_shape,
        selected_plane=selected_plane,
        cube_plane_is_explicit=explicit,
    )


def fits_image_from_arrays(
    path: str, data, header_mapping: dict, *, plane=None, allow_first_plane: bool = False, hdu_index: int = 0
) -> FitsImage:
    """Construye una `FitsImage` real a partir de píxeles y cabecera que
    ya están en memoria -- la vía por la que entra un XISF, sin pasar por
    ningún archivo temporal.

    Aplica exactamente el mismo manejo de cubos, WCS y escala de placa
    que `load_fits`: es el mismo motor, no una segunda implementación
    para el otro formato.
    """
    raw = _preserve_array_view(data)
    original_ndim, original_shape = raw.ndim, tuple(raw.shape)
    selected_plane: tuple[int, ...] | None = None
    explicit = True

    if raw.ndim > 2:
        if plane is not None:
            pixels, selected_plane = select_cube_plane(raw, plane)
        elif allow_first_plane:
            pixels, selected_plane = select_cube_plane(raw, 0)
            explicit = False
            LOG.warning(
                "%s: cubo %s sin plano explícito; usando plano 0 (SOLO vista rápida, no válido para análisis científico)",
                path, original_shape,
            )
        else:
            raise AmbiguousCubeError(
                f"{path}: la imagen tiene forma {original_shape} (ndim={raw.ndim}), no es una imagen 2D. "
                f"Indica explícitamente el plano/canal a usar en vez de asumir el primero por defecto."
            )
    else:
        pixels = raw

    if pixels.ndim != 2:
        raise AmbiguousCubeError(
            f"{path}: tras seleccionar plano, la forma sigue siendo {pixels.shape} (se requiere estrictamente 2D)."
        )

    header = dict(header_mapping)
    wcs, scale, source = _wcs_and_scale(_as_fits_header(header))
    if scale is None:
        scale = pixel_scale_from_wcs_header(header)
        if scale:
            source = "CDELT/PIXSCALE de la propia cabecera"

    return FitsImage(
        path=path,
        data=_preserve_array_view(pixels),
        header=header,
        pixel_scale_arcsec=scale,
        wcs=wcs,
        bunit=str(header.get("BUNIT", "")),
        exptime=_finite_or_none(header["EXPTIME"]) if "EXPTIME" in header else None,
        filter_name=str(header.get("FILTER", header.get("FILTER1", ""))),
        hdu_index=hdu_index,
        wcs_source=source,
        original_ndim=original_ndim,
        original_shape=original_shape,
        selected_plane=selected_plane,
        cube_plane_is_explicit=explicit,
    )


def probe_fits_shape(path: str, *, hdu: int | None = None) -> tuple[int, ...]:
    """Forma completa del HDU de imagen sin cargar un solo píxel -- solo
    la cabecera. Para poder preguntar al usuario qué plano de un cubo
    quiere sin tener que parsear el texto de `AmbiguousCubeError`."""
    with fits.open(str(path), memmap=True, lazy_load_hdus=True) as hdul:
        index = hdu if hdu is not None else _first_image_hdu_index(hdul)
        if index is None:
            raise ValueError(f"{path}: no hay HDU de imagen 2D")
        header = hdul[index].header
        naxis = int(header["NAXIS"])
        return tuple(int(header[f"NAXIS{i}"]) for i in range(naxis, 0, -1))


def resolve_path(path: str) -> str:
    return str(Path(path).resolve())
