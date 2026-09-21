"""Lectura ligera de cabeceras FITS -- sin tocar los píxeles, para poder
clasificar una sesión entera de archivos (ver
`reduction/frame_classification.py`) sin pagar el coste de cargar cada
imagen completa solo para leer cuatro palabras clave.

También reconoce un XISF real (por extensión o por su firma) y delega en
`xisf_reader.read_xisf_header` -- mismo tipo de retorno (`dict` plano),
para que el resto de esta función (clasificación de sesión) no tenga que
distinguir el formato de origen."""
from __future__ import annotations

from datetime import datetime, timezone

from astropy.io import fits

from astrophysics_suite.io.xisf_reader import is_xisf_path, read_xisf_header


def parse_date_obs(header: dict) -> datetime | None:
    """Instante real de adquisición a partir de `DATE-OBS` -- única
    implementación real (antes duplicada en `discovery/pipeline.py`,
    consolidada aquí para reutilizarla desde cualquier motor multiépoca,
    p. ej. `photometry/multi_frame.py`). Nunca se inventa: sin una
    cabecera FITS con `DATE-OBS` en un formato ISO 8601 reconocible,
    devuelve `None` -- quien llama decide qué hacer sin tiempo real."""
    raw = (header or {}).get("DATE-OBS")
    if not raw or not isinstance(raw, str):
        return None
    try:
        value = datetime.fromisoformat(raw.strip())
    except ValueError:
        return None
    return value if value.tzinfo is not None else value.replace(tzinfo=timezone.utc)


def read_fits_header(path: str) -> dict:
    """Devuelve la cabecera del primer HDU de imagen 2D+ de `path` como
    `dict` plano -- mismo tipo que expone `FitsImage.header` en
    `fits_loader.py`, para que el resultado se pueda tratar igual en
    cualquier otro sitio que ya espere un `dict` de cabecera."""
    if is_xisf_path(path):
        return dict(read_xisf_header(path))
    with fits.open(path, memmap=True, lazy_load_hdus=True) as hdul:
        for hdu in hdul:
            if getattr(hdu, "is_image", False) and hdu.header.get("NAXIS", 0) >= 2:
                return dict(hdu.header)
    raise ValueError(f"No se encontró ningún HDU de imagen en {path}")
