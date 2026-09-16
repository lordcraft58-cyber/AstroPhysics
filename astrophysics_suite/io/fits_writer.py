"""Escritura de FITS -- contrapartida simétrica de `fits_loader.load_image`.

La capa de ciencia (`reduction/`, `photometry/`, etc.) nunca toca disco --
devuelve arrays en memoria. Cuando un producto calibrado necesita
persistirse (p. ej. el pipeline de sesión de `reduction/session_pipeline.py`
desde la GUI), pasa por aquí, no por `astropy.io.fits` disperso en cada
diálogo de `qt_app/`.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits


def save_fits_image(
    path: str,
    data: np.ndarray,
    *,
    header: dict[str, Any] | fits.Header | None = None,
    overwrite: bool = True,
) -> None:
    """Escribe `data` como HDU primario de un FITS nuevo en `path`.

    `header` es opcional -- cuando viene de una `LoadedImage.legacy_image.header`
    (un `dict`), se copian solo las claves con valores serializables por
    FITS (escalar numérico/texto/booleano); claves problemáticas se omiten
    en vez de hacer fallar toda la escritura, igual que hace `astropy` con
    `HIERARCH` para claves largas.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.asarray(data, dtype=np.float32))
    if header is not None:
        items = header.items() if isinstance(header, (dict, fits.Header)) else []
        for key, value in items:
            if key in ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND"):
                continue
            if not isinstance(value, (int, float, bool, str)):
                continue
            try:
                hdu.header[key] = value
            except (ValueError, KeyError):
                continue
    hdu.writeto(path, overwrite=overwrite)
