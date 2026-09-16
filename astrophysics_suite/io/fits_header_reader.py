"""Lectura ligera de cabeceras FITS -- sin tocar los píxeles, para poder
clasificar una sesión entera de archivos (ver
`reduction/frame_classification.py`) sin pagar el coste de cargar cada
imagen completa solo para leer cuatro palabras clave.
"""
from __future__ import annotations

from astropy.io import fits


def read_fits_header(path: str) -> dict:
    """Devuelve la cabecera del primer HDU de imagen 2D+ de `path` como
    `dict` plano -- mismo tipo que expone `FitsImage.header` en
    `fits_loader.py`, para que el resultado se pueda tratar igual en
    cualquier otro sitio que ya espere un `dict` de cabecera."""
    with fits.open(path, memmap=True, lazy_load_hdus=True) as hdul:
        for hdu in hdul:
            if getattr(hdu, "is_image", False) and hdu.header.get("NAXIS", 0) >= 2:
                return dict(hdu.header)
    raise ValueError(f"No se encontró ningún HDU de imagen en {path}")
