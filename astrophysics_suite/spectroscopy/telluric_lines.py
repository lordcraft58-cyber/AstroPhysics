"""Bandas de absorción telúrica conocidas (§46) -- oxígeno molecular y
vapor de agua de la atmósfera terrestre, superpuestas a cualquier
espectro tomado desde el suelo. Posiciones ampliamente documentadas en
la literatura de espectroscopía estelar y en cualquier atlas de líneas
telúricas o espectro solar de referencia de alta resolución -- no son
datos ni código de ningún software de terceros.

Catálogo deliberadamente modesto, misma disciplina que `line_catalog.py`/
`standard_stars.py`: solo las bandas más fuertes e inequívocas, como
BANDAS (rango de longitud de onda) en vez de líneas individuales -- a la
resolución típica de un espectrógrafo de aficionado, la absorción
telúrica es un complejo de muchas líneas mezcladas, no una línea aislada,
así que representarla como una banda es más honesto que fingir una
posición de línea única.

Este módulo SOLO identifica solape -- verbatim del encargo (§46):
*"nunca eliminar automáticamente sin mostrar qué corrección se
aplicó"*. Ninguna corrección/sustracción telúrica se implementa aquí
todavía; eso exigiría un espectro de estrella estándar telúrica y queda
fuera de este slice.
"""
from __future__ import annotations

from dataclasses import dataclass

_REFERENCE = "atlas de líneas telúricas / espectro solar de referencia de alta resolución (bandas O2/H2O bien conocidas)"


@dataclass(frozen=True)
class TelluricBand:
    name: str
    species: str
    wavelength_start_angstrom: float
    wavelength_end_angstrom: float
    strength: str
    """Descriptivo (`"strong"`/`"moderate"`), nunca un número de
    profundidad inventado -- la profundidad real depende de la masa de
    aire y la humedad de cada observación concreta, no es una constante
    de catálogo."""
    reference: str = _REFERENCE


TELLURIC_BANDS: tuple[TelluricBand, ...] = (
    TelluricBand("O2 B", "O2", 6867.0, 6884.0, "strong"),
    TelluricBand("H2O 7200", "H2O", 7186.0, 7280.0, "moderate"),
    TelluricBand("O2 A", "O2", 7594.0, 7621.0, "strong"),
    TelluricBand("H2O 8200", "H2O", 8130.0, 8350.0, "moderate"),
    TelluricBand("H2O 9300-9700", "H2O", 9300.0, 9700.0, "strong"),
)
"""Ordenadas por longitud de onda creciente. El usuario puede tener
otras bandas relevantes para su rango espectral concreto no cubiertas
aquí -- lista deliberadamente corta y verificada, no exhaustiva."""


def find_telluric_overlap(wavelength_angstrom: float) -> TelluricBand | None:
    """La banda telúrica que cubre `wavelength_angstrom`, o `None` si
    ninguna del catálogo lo hace."""
    for band in TELLURIC_BANDS:
        if band.wavelength_start_angstrom <= wavelength_angstrom <= band.wavelength_end_angstrom:
            return band
    return None


def bands_overlapping_range(wavelength_min: float, wavelength_max: float) -> tuple[TelluricBand, ...]:
    """Todas las bandas del catálogo que solapan
    `[wavelength_min, wavelength_max]` -- p. ej. para marcarlas todas al
    mostrar un espectro completo, no solo una línea identificada."""
    if wavelength_max < wavelength_min:
        raise ValueError("wavelength_max debe ser >= wavelength_min")
    return tuple(
        band for band in TELLURIC_BANDS
        if band.wavelength_start_angstrom <= wavelength_max and band.wavelength_end_angstrom >= wavelength_min
    )
