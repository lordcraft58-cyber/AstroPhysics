"""Biblioteca de estrellas estándar espectrofotométricas al estilo
CALSPEC (§49) -- identidad pública de los patrones que usa la
comunidad para calibrar flujo, MÁS un lector del formato real de
archivo CALSPEC de STScI para alimentar `fluxcal.build_sensitivity_
function` con una referencia real.

Catálogo deliberadamente modesto, mismo criterio que `line_catalog.py`:
solo estrellas cuyo papel como patrón CALSPEC es inequívoco y de sobra
documentado (Bohlin, Gordon & Tremblay 2014, PASP 126, 711, y el propio
archivo público de STScI, https://www.stsci.edu/hst/instrumentation/
reference-data-for-calibration-and-tools/astronomical-catalogs/calspec.html).

NINGÚN valor de FLUJO se inventa ni se hardcodea aquí -- eso violaría
directamente el principio del encargo ("jamás inventar valores"). El
espectro de referencia real (longitud de onda + flujo físico) se lee
siempre de un archivo CALSPEC real descargado de STScI mediante
`load_calspec_spectrum`; este módulo solo aporta la identidad del
patrón (nombre/alias/tipo espectral/por qué se usa) para que el usuario
sepa qué está seleccionando, y el lector del formato de archivo. Las
coordenadas del objeto, si hacen falta, se resuelven contra SIMBAD
(motor ya existente, Fase "resolución de coordenadas por nombre") en
vez de duplicarlas aquí con riesgo de quedarse desactualizadas.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from astropy.io import fits

_REFERENCE = "Bohlin, Gordon & Tremblay (2014), PASP 126, 711 -- CALSPEC"


@dataclass(frozen=True)
class StandardStarInfo:
    name: str
    aliases: tuple[str, ...]
    spectral_type: str
    role: str
    """Por qué se usa como patrón (p. ej. "enana blanca DA, patrón
    primario CALSPEC" o "patrón espectrofotométrico histórico")."""
    reference: str = _REFERENCE


CALSPEC_STANDARD_STARS: tuple[StandardStarInfo, ...] = (
    StandardStarInfo("Vega", ("alpha Lyr", "alf Lyr", "HD 172167"), "A0V", "patrón espectrofotométrico histórico"),
    StandardStarInfo("Sirius", ("alpha CMa", "alf CMa", "HD 48915"), "A1V", "patrón espectrofotométrico CALSPEC"),
    StandardStarInfo("G191-B2B", (), "DA (enana blanca)", "patrón primario CALSPEC (enana blanca DA)"),
    StandardStarInfo("GD 71", ("GD71",), "DA (enana blanca)", "patrón primario CALSPEC (enana blanca DA)"),
    StandardStarInfo("GD 153", ("GD153",), "DA (enana blanca)", "patrón primario CALSPEC (enana blanca DA)"),
    StandardStarInfo("HZ 43", ("HZ43",), "DA (enana blanca)", "patrón espectrofotométrico CALSPEC (enana blanca DA)"),
)
"""Deliberadamente modesto (misma disciplina que `line_catalog.py`):
mejor una lista corta y verificada que una larga con alguna
clasificación sin confirmar. El usuario puede usar cualquier otra
estrella CALSPEC pasando directamente su archivo a
`load_calspec_spectrum` -- esta lista es solo una ayuda de catálogo,
nunca una restricción de qué se puede calibrar."""


def find_standard_star(name: str) -> StandardStarInfo | None:
    """Busca por nombre o alias (sin distinguir mayúsculas ni espacios
    sobrantes). Devuelve `None` si no está en este catálogo modesto --
    nunca la "más parecida"."""
    normalized = name.strip().casefold()
    for star in CALSPEC_STANDARD_STARS:
        if star.name.casefold() == normalized or any(alias.casefold() == normalized for alias in star.aliases):
            return star
    return None


@dataclass(frozen=True)
class CalspecSpectrum:
    wavelength_angstrom: np.ndarray
    flux: np.ndarray
    """Flujo físico tal cual lo da el archivo CALSPEC -- ver `flux_unit`
    para sus unidades reales (normalmente erg/s/cm^2/Angstrom), nunca
    reescaladas ni normalizadas aquí."""
    flux_unit: str
    flux_uncertainty: np.ndarray | None
    """`None` si el archivo no traía columna de error estadístico -- no
    se inventa una incertidumbre que el archivo no da."""
    header: dict


_WAVELENGTH_COLUMN_CANDIDATES = ("WAVELENGTH", "WAVE", "LAMBDA")
_FLUX_COLUMN_CANDIDATES = ("FLUX",)
_FLUX_ERROR_COLUMN_CANDIDATES = ("STATERROR", "STAT_ERROR", "ERROR")


def load_calspec_spectrum(path: str) -> CalspecSpectrum:
    """Lee un archivo CALSPEC real (descargado de STScI) -- tabla
    binaria con columnas `WAVELENGTH` (Å) y `FLUX` (densidad de flujo
    física, típicamente erg/s/cm^2/Å), más `STATERROR` si el archivo la
    trae. Es el formato público y estable que documenta STScI, no una
    convención de este proyecto ni de ningún software de terceros.

    Busca la primera extensión de tabla binaria que tenga columnas
    reconocibles de longitud de onda y flujo -- lanza `ValueError` con
    un mensaje claro si no encuentra ninguna, en vez de adivinar qué
    columna podría ser cuál.
    """
    with fits.open(path) as hdul:
        for hdu in hdul:
            columns = getattr(hdu, "columns", None)
            if columns is None:
                continue
            names_upper = {c.upper(): c for c in columns.names}
            wavelength_col = next((names_upper[c] for c in _WAVELENGTH_COLUMN_CANDIDATES if c in names_upper), None)
            flux_col = next((names_upper[c] for c in _FLUX_COLUMN_CANDIDATES if c in names_upper), None)
            if wavelength_col is None or flux_col is None:
                continue
            error_col = next((names_upper[c] for c in _FLUX_ERROR_COLUMN_CANDIDATES if c in names_upper), None)
            wavelength = np.asarray(hdu.data[wavelength_col], dtype=np.float64).reshape(-1)
            flux = np.asarray(hdu.data[flux_col], dtype=np.float64).reshape(-1)
            uncertainty = (
                np.asarray(hdu.data[error_col], dtype=np.float64).reshape(-1) if error_col is not None else None
            )
            flux_unit = str(columns[flux_col].unit or "erg/s/cm^2/Angstrom")
            return CalspecSpectrum(
                wavelength_angstrom=wavelength, flux=flux, flux_unit=flux_unit,
                flux_uncertainty=uncertainty, header=dict(hdul[0].header),
            )
    raise ValueError(
        f"{path!r} no tiene ninguna extensión de tabla con columnas de longitud de onda/flujo reconocibles "
        f"(se buscó {_WAVELENGTH_COLUMN_CANDIDATES} + {_FLUX_COLUMN_CANDIDATES}) -- "
        "¿es un archivo CALSPEC real?"
    )
