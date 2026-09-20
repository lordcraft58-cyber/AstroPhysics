"""Escritura de FITS -- contrapartida simétrica de `fits_loader.load_image`.

La capa de ciencia (`reduction/`, `photometry/`, etc.) nunca toca disco --
devuelve arrays en memoria. Cuando un producto calibrado necesita
persistirse (p. ej. el pipeline de sesión de `reduction/session_pipeline.py`
desde la GUI), pasa por aquí, no por `astropy.io.fits` disperso en cada
diálogo de `qt_app/`.
"""
from __future__ import annotations

import textwrap
import unicodedata
from pathlib import Path
from typing import Any

import numpy as np
from astropy.io import fits


UNCERTAINTY_EXTENSION_NAME = "UNCERT"
"""Mismo nombre de extensión que ya usan los fotogramas maestros
(`reduction/master_frames.py`) para su incertidumbre -- una sola
convención en todo el producto, no una por motor."""

_STRUCTURAL_KEYS = ("SIMPLE", "BITPIX", "NAXIS", "NAXIS1", "NAXIS2", "EXTEND")

_SCALING_KEYS = ("BZERO", "BSCALE", "BLANK")
"""Estas NO describen la imagen: describen cómo estaban representados los
enteros del archivo de ORIGEN. Copiarlas a un archivo nuevo escrito en
coma flotante corrompe todos los píxeles en silencio -- `astropy` aplica
`dato * BSCALE + BZERO` al releer. Con las cámaras reales del usuario
(ZWO ASI533MC Pro, BITPIX=16 con BZERO=32768) eso desplazaba cada píxel
calibrado en +32768 ADU, y el archivo seguía pareciendo correcto.
Detectado con los LIGHTS reales de M 31, no en pruebas sintéticas.
"""


def ascii_safe(text: str) -> str:
    """El estándar FITS solo admite ASCII imprimible en las tarjetas, y
    todo este producto escribe en castellano. Se translitera (ó -> o,
    ñ -> n) en vez de descartar el valor entero: antes, cualquier cadena
    con tilde se perdía en silencio por el `except ValueError` de abajo,
    que es justo lo que este proyecto no hace."""
    if text.isascii():
        return text
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c if c.isascii() and c.isprintable() else "?" for c in stripped)


_HISTORY_PAYLOAD_CHARS = 72
"""Una tarjeta `HISTORY` son 8 caracteres de clave más 72 de texto. Si
una línea se pasa, `astropy` la parte por donde caiga -- y parte
palabras por la mitad (`... a 749 m` / `m`, que ya no se puede ni
buscar en el archivo). Se parte aquí, por espacios, antes de
entregarla -- hallazgo original de `astrometry/provenance.py`,
promovido aquí porque cualquier motor que escriba HISTORY largo en
castellano tiene el mismo problema, no solo ese."""


def wrap_history_lines(lines: list[str], *, prefix: str = "") -> list[str]:
    """Prefija la primera línea (si se da `prefix`) e indenta las demás,
    partiendo por palabras lo que no quepa en una tarjeta `HISTORY`."""
    wrapped: list[str] = []
    for index, line in enumerate(lines):
        text = f"{prefix} {line}" if index == 0 and prefix else line if index == 0 else f"  {line}"
        wrapped.extend(
            textwrap.wrap(text, width=_HISTORY_PAYLOAD_CHARS, subsequent_indent="    ", break_long_words=False)
            or [text]
        )
    return wrapped


def save_fits_image(
    path: str,
    data: np.ndarray,
    *,
    header: dict[str, Any] | fits.Header | None = None,
    uncertainty: np.ndarray | None = None,
    overwrite: bool = True,
) -> None:
    """Escribe `data` como HDU primario de un FITS nuevo en `path`.

    `header` es opcional -- cuando viene de una `LoadedImage.legacy_image.header`
    (un `dict`), se copian solo las claves con valores serializables por
    FITS (escalar numérico/texto/booleano); claves problemáticas se omiten
    en vez de hacer fallar toda la escritura, igual que hace `astropy` con
    `HIERARCH` para claves largas. La clave `HISTORY` acepta además una
    lista de líneas, que se escriben como tarjetas `HISTORY` reales (así
    es como la reducción declara qué pasos aplicó, ver
    `reduction/provenance.py`).

    Las palabras clave de escalado del archivo de origen (`BZERO`,
    `BSCALE`, `BLANK`) se descartan siempre: pertenecen a la
    representación entera de aquel archivo, no a estos datos.

    `uncertainty`, si se da, se escribe como extensión `UNCERT` real con
    la misma forma -- antes se descartaba al guardar aunque el motor la
    hubiera propagado con cuidado, y con ella se perdía la única medida
    honesta del error de cada píxel.
    """
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    hdu = fits.PrimaryHDU(data=np.asarray(data, dtype=np.float32))
    if header is not None:
        items = header.items() if isinstance(header, (dict, fits.Header)) else []
        for key, value in items:
            if key in _STRUCTURAL_KEYS or key in _SCALING_KEYS:
                continue
            if key == "HISTORY":
                lines = value if isinstance(value, (list, tuple)) else [value]
                for line in lines:
                    hdu.header.add_history(ascii_safe(str(line)))
                continue
            if not isinstance(value, (int, float, bool, str)):
                continue
            try:
                hdu.header[key] = ascii_safe(value) if isinstance(value, str) else value
            except (ValueError, KeyError):
                continue

    hdus: list[fits.hdu.base._BaseHDU] = [hdu]
    if uncertainty is not None:
        uncertainty_array = np.asarray(uncertainty, dtype=np.float32)
        if uncertainty_array.shape != np.asarray(data).shape:
            raise ValueError(
                f"la incertidumbre {uncertainty_array.shape} no tiene la misma forma que los datos {np.asarray(data).shape}"
            )
        hdus.append(fits.ImageHDU(data=uncertainty_array, name=UNCERTAINTY_EXTENSION_NAME))

    fits.HDUList(hdus).writeto(path, overwrite=overwrite)
