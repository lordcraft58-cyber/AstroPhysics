"""Clasificación de fotogramas por cabecera -- equivalente propio de
`ccdlist` de IRAF: identificar si un archivo es un bias, un dark, un flat
o una LIGHT a partir de las palabras clave de tipo de imagen que casi
cualquier cámara/software de adquisición escribe (`IMAGETYP`, `OBSTYPE`,
`FRAMETYP`), para que una sesión completa pueda clasificarse sola en vez
de que el usuario elija cada archivo a mano en cada diálogo.

Nunca adivina: si ninguna palabra clave reconocida está presente, o su
valor no coincide con ningún patrón conocido, el fotograma se clasifica
como `"unknown"` -- la misma disciplina de honestidad epistémica que rige
el resto del proyecto, aplicada aquí a la gestión de sesiones.
"""
from __future__ import annotations

from dataclasses import dataclass

_HEADER_KEYS = ("IMAGETYP", "OBSTYPE", "FRAMETYP")

_BIAS_VALUES = {"bias", "bias frame", "zero", "zero frame"}
_DARK_VALUES = {"dark", "dark frame"}
_FLAT_VALUES = {"flat", "flat field", "flatfield", "flat frame", "domeflat", "dome flat", "skyflat", "sky flat"}
_LIGHT_VALUES = {"light", "light frame", "object", "science", "science frame"}

FRAME_TYPES = ("bias", "dark", "flat", "light", "unknown")


def classify_frame_type(header: dict) -> str:
    """Inspecciona `header` (un `dict` plano, p. ej. de
    `io.fits_header_reader.read_fits_header`) y devuelve uno de
    `FRAME_TYPES`. Prueba las palabras clave en orden hasta encontrar una
    presente; si ninguna lo está, o su valor no se reconoce, devuelve
    `"unknown"` -- nunca infiere el tipo a partir de otra cosa (nombre de
    archivo, forma de la imagen, etc.)."""
    for key in _HEADER_KEYS:
        value = header.get(key)
        if value is None:
            continue
        normalized = str(value).strip().lower()
        if normalized in _BIAS_VALUES:
            return "bias"
        if normalized in _DARK_VALUES:
            return "dark"
        if normalized in _FLAT_VALUES:
            return "flat"
        if normalized in _LIGHT_VALUES:
            return "light"
    return "unknown"


@dataclass(frozen=True)
class ClassifiedFrame:
    path: str
    frame_type: str
    exposure_s: float | None
    filter_name: str


def classify_session_headers(headers_by_path: dict[str, dict]) -> list[ClassifiedFrame]:
    """Clasifica cada archivo de `headers_by_path` (ruta -> cabecera ya
    leída) y extrae `EXPTIME`/`FILTER` de paso, para que la GUI pueda
    mostrar un resumen útil sin releer nada. El orden del resultado
    sigue el de `headers_by_path`."""
    results = []
    for path, header in headers_by_path.items():
        frame_type = classify_frame_type(header)
        exposure = header.get("EXPTIME")
        filter_name = str(header.get("FILTER") or "")
        results.append(
            ClassifiedFrame(
                path=path,
                frame_type=frame_type,
                exposure_s=float(exposure) if exposure is not None else None,
                filter_name=filter_name,
            )
        )
    return results
