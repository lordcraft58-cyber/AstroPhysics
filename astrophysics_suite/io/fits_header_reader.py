"""Lectura ligera de cabeceras FITS -- sin tocar los píxeles, para poder
clasificar una sesión entera de archivos (ver
`reduction/frame_classification.py`) sin pagar el coste de cargar cada
imagen completa solo para leer cuatro palabras clave.

También reconoce un XISF real (por extensión o por su firma) y delega en
`xisf_reader.read_xisf_header` -- mismo tipo de retorno (`dict` plano),
para que el resto de esta función (clasificación de sesión) no tenga que
distinguir el formato de origen."""
from __future__ import annotations

from astropy.io import fits

from astrophysics_suite.io.xisf_reader import is_xisf_path, read_xisf_header


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
