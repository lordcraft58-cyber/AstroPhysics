"""Procedencia de una calibración en longitud de onda: de qué motor
salió, con qué evidencia real, y qué avisos honestos lleva encima --
el mismo principio que ya cierra `astrometry/provenance.py` y
`reduction/provenance.py`, aplicado aquí porque una calibración
espectral es exactamente el mismo tipo de afirmación que un WCS: o hay
medida real detrás, o no la hay, y el archivo tiene que decir cuál de
las dos.

Punto 11 del encargo, verbatim: *"jamás debe presentar una calibración
inventada como calibración medida de una observación real"*. Este
módulo es la puerta que lo hace cumplir -- cualquier `WavelengthSolution`
que llegue a un FITS pasa por aquí primero.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.spectroscopy.wavelength import WavelengthSolution

ENGINE_NAME = "spectroscopy.wavelength"
ENGINE_VERSION = "1.0"

MIN_LINES_PER_DEGREE = 2
"""Con menos de `degree * MIN_LINES_PER_DEGREE` líneas, el ajuste tiene
muy pocos grados de libertad para evaluar su propia calidad -- mismo
espíritu que el hallazgo de `astrometry.provenance.
MIN_STARS_FOR_MEANINGFUL_RMS` (3 estrellas para un TAN de 2 parámetros
por eje dan un RMS que no mide nada).

Medido, no supuesto: grado 3, 0.15 px de error real de centroide de
línea de arco, dispersión ~1.4 Å/px, 300 ajustes por tamaño de muestra:

    n=4 (=grado+1)  RMS declarado=0.00000 Å   error real=1.7208 Å   (ratio ~10^9)
    n=6             RMS declarado=0.52547 Å   error real=0.7423 Å   (1.41x)
    n=8             RMS declarado=0.71013 Å   error real=0.5759 Å   (0.81x)
    n=12            RMS declarado=0.91044 Å   error real=0.4092 Å   (0.45x)
    n=20            RMS declarado=1.10746 Å   error real=0.3048 Å   (0.28x)

Con `n = grado + 1` (el mínimo que admite `fit_wavelength_solution`) el
ajuste interpola exactamente esos puntos: el RMS declarado es ~0 por
construcción, sin relación con el error real fuera de esos puntos. De
`n = 2*grado` en adelante el RMS ya es del orden correcto; de ahí en
adelante es conservador (declara más error del que comete)."""


class CalibrationSource(Enum):
    """De dónde sale de verdad la solución -- nunca "se ve bien" o "se
    supone"."""

    LAMP_REAL = "lamp_real"
    """Líneas de una lámpara de calibración real, identificadas contra
    un catálogo (`line_catalog.py`) y confirmadas."""
    REUSED_INSTRUMENTAL = "reused_instrumental"
    """Solución previamente validada para este instrumento, reutilizada
    (§12) -- puede llevar un desplazamiento global reajustado, nunca un
    reajuste completo sin nueva evidencia."""
    REFERENCE_STAR = "reference_star"
    """Inferida de líneas espectrales conocidas de una estrella de
    referencia (§13) -- calibración PROVISIONAL, nunca al nivel de una
    lámpara real: la posición de una línea estelar depende también de
    velocidad radial y ensanchamiento, no solo de la óptica."""
    SYNTHETIC = "synthetic"
    """Generada artificialmente para pruebas (§33) -- NUNCA se presenta
    como calibración de una observación real."""


_SOURCE_LABELS = {
    CalibrationSource.LAMP_REAL: "lámpara de calibración real",
    CalibrationSource.REUSED_INSTRUMENTAL: "solución instrumental reutilizada",
    CalibrationSource.REFERENCE_STAR: "inferida de estrella de referencia",
    CalibrationSource.SYNTHETIC: "SINTÉTICA (no es una calibración real)",
}


@dataclass(frozen=True)
class WavelengthCalibrationRecord:
    solution: WavelengthSolution
    source: CalibrationSource
    n_lines_used: int
    n_lines_rejected: int = 0
    lamp_name: str | None = None
    """P. ej. `"Ne"`, `"Ar"`, `"HeNeAr"` -- solo con `LAMP_REAL`."""
    reference_object: str | None = None
    """Solo con `REFERENCE_STAR`: qué estrella se usó."""
    offset_only_reidentified: bool = False
    """`True` cuando un perfil `REUSED_INSTRUMENTAL` no se reutilizó tal
    cual, sino que se le recalculó SOLO el desplazamiento global A0 por
    correlación cruzada (`services.spectral_calibration_profiles.
    reidentify_profile_offset`, §12) -- la forma del polinomio sigue
    siendo la validada originalmente, sin nueva evidencia de líneas.
    Dispara el aviso de posible deriva mecánica/térmica del encargo."""

    @property
    def is_synthetic(self) -> bool:
        return self.source is CalibrationSource.SYNTHETIC

    @property
    def is_measured(self) -> bool:
        """`True` si hay evidencia espectral real detrás -- incluye
        `REFERENCE_STAR` (evidencia real, aunque menos fiable que una
        lámpara), excluye `SYNTHETIC`."""
        return self.source is not CalibrationSource.SYNTHETIC

    def describe(self) -> tuple[str, ...]:
        label = _SOURCE_LABELS[self.source]
        lines = [f"calibración en longitud de onda: {label}"]
        if self.lamp_name:
            lines.append(f"lámpara: {self.lamp_name}")
        if self.reference_object:
            lines.append(f"estrella de referencia: {self.reference_object}")
        lines.append(
            f"ajuste de grado {self.solution.degree} con {self.n_lines_used} línea(s) "
            f"(rechazadas: {self.n_lines_rejected}), RMS = {self.solution.rms_residual:.4f}"
        )
        if self.offset_only_reidentified:
            lines.append("solo se recalculó el desplazamiento global (A0); la forma del polinomio no es nueva evidencia")
        return tuple(lines)


def build_wavelength_provenance(record: WavelengthCalibrationRecord, *, pipeline_version: str = "") -> Provenance:
    """`Provenance` real de la calibración, con los avisos que el propio
    dato obliga a dar -- nunca ocultos, nunca fuera del archivo."""
    warnings: list[str] = []
    if record.is_synthetic:
        warnings.append("CALIBRACIÓN SIMULADA: generada para pruebas, no mide ninguna observación real")
    if record.source is CalibrationSource.REFERENCE_STAR:
        warnings.append(
            "calibración inferida de una estrella de referencia, no de una lámpara: "
            "la posición de una línea estelar depende también de velocidad radial y ensanchamiento"
        )
    if record.offset_only_reidentified:
        warnings.append(
            "solución instrumental reutilizada con solo el desplazamiento global recalculado (§12): "
            "un cambio mecánico o térmico real del instrumento puede haber desplazado el espectro "
            "de una forma que una correlación cruzada de un solo desplazamiento no puede detectar"
        )
    min_lines = record.solution.degree * MIN_LINES_PER_DEGREE
    if record.n_lines_used < min_lines and record.solution.degree > 0:
        warnings.append(
            f"ajuste de grado {record.solution.degree} con solo {record.n_lines_used} línea(s): "
            f"se recomiendan al menos {min_lines} para que el RMS declarado sea representativo"
        )
    if record.n_lines_used <= record.solution.degree + 1:
        warnings.append(
            f"grado {record.solution.degree} con {record.n_lines_used} línea(s): el ajuste no tiene "
            "grados de libertad de sobra, el RMS puede ser artificialmente bajo"
        )

    return Provenance.now(
        pipeline_version=pipeline_version,
        engine=ENGINE_NAME,
        engine_version=ENGINE_VERSION,
        warnings=tuple(warnings),
    )
