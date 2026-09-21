"""Atlas de espectros estándar Jacoby, Hunter & Christian (1984, ApJS,
56, 257, "A library of stellar spectra") -- biblioteca real y publicada
que cubre la secuencia MK completa (O5 a M7, clases de luminosidad I a
V), aportada directamente por el usuario (su propia copia, ya incluida
en el programa Vireo que usa para clasificación espectral) e incluida
aquí tal cual: 161 espectros reales de estrellas concretas (HD/BD/SAO),
en `spectroscopy/data/jacoby_atlas/` -- `JACOBY2.INX` (el índice real,
formato de columnas fijas del propio atlas) más un `.SP` real por
estrella (longitud de onda en Å, flujo, mismo formato de dos columnas
que ya lee `spectrum1d_io.import_ascii_spectrum`).

Ninguna clasificación automática aquí (§25/§26, mismo principio que
`template_comparison.py`): este módulo solo permite ENCONTRAR y CARGAR
el espectro estándar real que el usuario elija por tipo espectral --
la comparación real (`template_comparison.compare_to_template`) y la
decisión de qué significa el residuo siguen siendo del usuario.
"""
from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path

import numpy as np

from astrophysics_suite.spectroscopy.spectrum1d_io import import_ascii_spectrum

_LUMINOSITY_SUFFIXES: tuple[str, ...] = ("III", "II", "IV", "V", "I")
"""Orden de comprobación deliberado (más específico primero): el campo
de 7 caracteres del `.INX` combina tipo espectral y clase de luminosidad
sin separador fijo (p. ej. `"O6.5III"`, `"O5    V"`, `"B1    I"`) --
probar "III" antes que "I" evita partir mal "III" en "I"+"I"+resto."""


@dataclass(frozen=True)
class JacobyAtlasEntry:
    index: int
    """Número real de catálogo (1-161) -- también el nombre del archivo
    `.SP` real que le corresponde (`A{index:07d}.SP`)."""
    name: str
    """Designación real del catálogo de origen (HD/BD/SAO/Feige...),
    tal cual la trae el `.INX` real -- nunca inventada."""
    spectral_type: str
    luminosity_class: str
    color1: float
    """Primer índice de color real del `.INX` (U-B, según la
    documentación original del atlas)."""
    color2: float
    """Segundo índice de color real del `.INX` (B-V)."""

    @property
    def label(self) -> str:
        return f"{self.spectral_type} {self.luminosity_class} -- {self.name}"


def _parse_index_line(line: str) -> JacobyAtlasEntry:
    """Formato de columnas FIJAS real del `.INX` (heredado, sin
    separador fiable por espacios: un nombre como `"HD 227018"` y un
    campo combinado `"O6.5III"` sin espacio entre tipo y luminosidad
    rompen un `split()` ingenuo) -- verificado contra los 161 registros
    reales: índice en `[0:5]`, nombre en `[5:16]`, tipo+luminosidad en
    `[16:23]`, el resto (color1/color2/desplazamiento real del `.SPI`
    original, no usado aquí) separado por espacios."""
    index = int(line[0:5])
    name = line[5:16].strip()
    combined = line[16:23].rstrip()
    for suffix in _LUMINOSITY_SUFFIXES:
        if combined.endswith(suffix):
            spectral_type = combined[: -len(suffix)].strip()
            luminosity_class = suffix
            break
    else:
        raise ValueError(f"no se reconoce la clase de luminosidad en {combined!r} (línea real: {line!r})")
    rest = line[23:].split()
    color1, color2 = float(rest[0]), float(rest[1])
    return JacobyAtlasEntry(
        index=index, name=name, spectral_type=spectral_type, luminosity_class=luminosity_class,
        color1=color1, color2=color2,
    )


def load_jacoby_atlas_index(inx_path: str | Path) -> tuple[JacobyAtlasEntry, ...]:
    """Las 161 entradas reales del atlas, en el orden real del `.INX`
    -- nunca inventa una entrada que el archivo no traiga."""
    with open(inx_path, encoding="latin-1") as handle:
        lines = [line.rstrip("\r\n") for line in handle]
    entries = [_parse_index_line(line) for line in lines if line.strip() and line.strip()[0].isdigit()]
    if not entries:
        raise ValueError(f"«{inx_path}» no trae ninguna entrada real reconocible del atlas")
    return tuple(entries)


def load_jacoby_atlas_spectrum(entry: JacobyAtlasEntry, spectra_dir: str | Path) -> tuple[np.ndarray, np.ndarray]:
    """`(wavelength, flux)` real del `.SP` de `entry` -- reutiliza
    `import_ascii_spectrum` (mismo formato de dos columnas, sin
    cabecera real en este atlas) en vez de reimplementar el parseo."""
    path = Path(spectra_dir) / f"A{entry.index:07d}.SP"
    if not path.exists():
        raise ValueError(f"falta el espectro real de «{entry.label}» -- se esperaba en {path}")
    wavelength, flux, _header_line = import_ascii_spectrum(str(path))
    return wavelength, flux


def bundled_atlas_paths() -> tuple[Path, Path]:
    """Rutas reales `(inx_path, spectra_dir)` de la copia del atlas ya
    incluida en este proyecto (aportada por el usuario, ver docstring
    del módulo) -- para el uso normal desde la GUI; `load_jacoby_atlas_
    index`/`load_jacoby_atlas_spectrum` siguen aceptando cualquier otra
    copia real del atlas si el llamador prefiere apuntar a la suya."""
    root = resources.files("astrophysics_suite.spectroscopy") / "data" / "jacoby_atlas"
    inx_path = Path(str(root / "JACOBY2.INX"))
    spectra_dir = Path(str(root / "spectra"))
    if not inx_path.exists() or not spectra_dir.is_dir():
        raise ValueError(f"no se encuentra la copia incluida del atlas Jacoby-Hunter-Christian en {root}")
    return inx_path, spectra_dir
