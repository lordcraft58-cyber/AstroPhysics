"""Procedencia de una solución astrométrica y sus tarjetas FITS.

Un `WCSSolution` no dice de dónde salió. Cuatro motores muy distintos lo
producen -- `plate_solve` (emparejamiento contra Gaia con puntero),
`blind_solve` (hashing geométrico sin puntero), `wcs_fit` (el usuario
marca estrellas a clic) y `optical_wcs` (geometría declarada desde la
cámara y la focal) -- y la diferencia entre ellos importa muchísimo al
leer el archivo después: solo los tres primeros MIDEN algo.

Hasta ahora la copia FITS con WCS se escribía desde la propia ventana
Qt, con las tarjetas construidas a mano ahí mismo, y la línea `HISTORY`
decía siempre `astrometry.wcs_fit` -- incluso cuando la placa se había
resuelto en ciego. Este módulo traslada esa lógica a la capa de ciencia,
donde se puede probar sin Qt, y hace que el archivo diga qué motor lo
resolvió de verdad.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

from astrophysics_suite.astrometry.optical_wcs import is_optical_wcs, pixel_scale_of
from astrophysics_suite.astrometry.wcs_fit import WCSSolution, wcs_solution_to_astropy
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.io.fits_writer import wrap_history_lines

SOURCE_PLATE_SOLVE = "astrometry.plate_solve"
SOURCE_BLIND_SOLVE = "astrometry.blind_solve"
SOURCE_MANUAL_FIT = "astrometry.wcs_fit"
SOURCE_OPTICS = "astrometry.optical_wcs"

_SOURCE_LABELS = {
    SOURCE_PLATE_SOLVE: "resolución automática de placa contra catálogo",
    SOURCE_BLIND_SOLVE: "resolución de placa en ciego (sin puntero)",
    SOURCE_MANUAL_FIT: "ajuste manual sobre estrellas marcadas a clic",
    SOURCE_OPTICS: "geometría declarada desde la óptica (cámara + focal)",
}

MIN_STARS_FOR_MEANINGFUL_RMS = 4
"""Por debajo de esto el RMS declarado no mide el error del ajuste.

No es un número de tradición: se midió. Con el WCS real del usuario
(ASI533MC Pro a 749 mm, 1.0355 "/px) y un error de centroide de 0.5 px,
400 ajustes por tamaño de muestra dan

    n= 3  RMS declarado=0.0032"   error real en el centro=0.7369"  (230x)
    n= 4  RMS declarado=0.3233"   error real en el centro=0.4545"  (1.4x)
    n= 6  RMS declarado=0.4894"   error real en el centro=0.3299"  (0.7x)
    n=30  RMS declarado=0.6923"   error real en el centro=0.1150"  (0.2x)

Con 3 estrellas `fit_wcs` resuelve CRVAL con tantas ecuaciones como
incógnitas: los residuales salen casi nulos por construcción y el RMS
queda 230 veces por debajo del error real. Un usuario que lea
`WCSRMS = 0.003` creerá tener astrometría de milisegundos de arco
teniendo 0.74". De 4 en adelante el RMS ya es del orden correcto, y de
6 en adelante es conservador (declara más error del que comete). Por eso
el aviso salta por debajo de 4, y por eso va escrito en el archivo.
"""

_STALE_WCS_KEYS = frozenset(
    {
        "WCSAXES", "CTYPE1", "CTYPE2", "CUNIT1", "CUNIT2",
        "CRVAL1", "CRVAL2", "CRPIX1", "CRPIX2",
        "CDELT1", "CDELT2", "CROTA1", "CROTA2",
        "LONPOLE", "LATPOLE", "EQUINOX", "RADESYS", "RADECSYS",
        "A_ORDER", "B_ORDER", "AP_ORDER", "BP_ORDER",
        "WCSRMS", "WCSNSTR",
    }
)

_STALE_WCS_PATTERNS = (
    re.compile(r"^CD[12]_[12]$"),            # matriz CD
    re.compile(r"^PC[12]_[12]$"),            # matriz PC alternativa
    re.compile(r"^PV\d+_\d+$"),              # distorsión TPV
    re.compile(r"^(A|B|AP|BP)_\d+_\d+$"),    # coeficientes SIP
    re.compile(r"^APSWCS"),                  # procedencia de un WCS anterior nuestro
)


def is_wcs_keyword(key: str) -> bool:
    """`True` si la tarjeta describe una solución astrométrica (o su
    procedencia), y por tanto deja de ser cierta en cuanto la solución
    cambia."""
    upper = key.upper()
    return upper in _STALE_WCS_KEYS or any(p.match(upper) for p in _STALE_WCS_PATTERNS)


def strip_wcs_keywords(header: dict) -> dict:
    """Copia de `header` sin ninguna tarjeta de WCS: el punto de partida
    obligatorio antes de escribir una solución nueva.

    **Encontrado con un LIGHT real de M 31.** El ASIAIR Mini del usuario
    ya había resuelto la placa y dejó en la cabecera una solución TAN-SIP
    completa: `CTYPE1 = 'RA---TAN-SIP'`, `CRPIX` en (2742, 1803) y 24
    coeficientes `A_*`/`B_*`/`AP_*`/`BP_*`. Al escribir encima el WCS
    nuevo, `CTYPE`/`CRVAL`/`CRPIX`/`CD` se sobrescribían... y **los
    coeficientes SIP se quedaban**. `astropy` los aplica igualmente
    (avisa: "SIP coefficients were detected... the coordinates calculated
    here might be incorrect") sobre una solución lineal que no los
    contempla: hasta **0.56 arcsec (0.54 px) de error en las esquinas**,
    cero en el centro, así que ninguna comprobación centrada lo ve. Y
    como cada programa decide por su cuenta si aplicarlos, el mismo
    archivo significaba cosas distintas en programas distintos.
    """
    return {key: value for key, value in header.items() if not is_wcs_keyword(key)}


ENGINE_NAME = "astrometry.provenance"
ENGINE_VERSION = "1.0"

_HISTORY_PREFIX = "AstroPhysics Suite:"


@dataclass(frozen=True)
class WCSRecord:
    """Una solución astrométrica MÁS de dónde salió."""

    solution: WCSSolution
    source: str
    """Uno de los `SOURCE_*` de este módulo: el motor que la produjo de
    verdad, no el que resulte cómodo nombrar."""
    engine_version: str = "1.0"
    catalog: str | None = None
    """Catálogo contra el que se ajustó, si lo hubo (p. ej. `Gaia DR3`).
    `None` para un ajuste manual o una construcción óptica."""
    n_detected_stars: int | None = None
    n_matched_stars: int | None = None
    optics_description: str | None = None
    """Para `SOURCE_OPTICS`: qué óptica declaró el usuario (cámara,
    focal). Es la única trazabilidad posible de esa solución."""

    @property
    def is_measured(self) -> bool:
        """`True` si hay un ajuste real contra estrellas detrás. Una
        construcción óptica es geometría declarada: exacta en escala,
        pero sin ninguna medida de su propio error."""
        return not is_optical_wcs(self.solution)

    @property
    def pixel_scale_arcsec(self) -> float:
        return pixel_scale_of(self.solution)

    def describe(self) -> tuple[str, ...]:
        """Lista legible de lo que de verdad se sabe de esta solución."""
        label = _SOURCE_LABELS.get(self.source, self.source)
        lines = [f"WCS por {label} ({self.source} {self.engine_version})"]
        if self.is_measured:
            lines.append(
                f"ajustado con {self.solution.n_stars} estrella(s), "
                f"RMS = {self.solution.rms_residual_arcsec:.4f} arcsec"
            )
        else:
            lines.append("sin ajuste contra estrellas: no tiene error medido")
            if self.optics_description:
                lines.append(f"optica declarada: {self.optics_description}")
        if self.catalog:
            lines.append(f"catalogo de referencia: {self.catalog}")
        if self.n_detected_stars is not None and self.n_matched_stars is not None:
            lines.append(f"{self.n_matched_stars} de {self.n_detected_stars} estrella(s) detectada(s) emparejada(s)")
        lines.append(f"escala resultante: {self.pixel_scale_arcsec:.4f} arcsec/px")
        return tuple(lines)


def build_wcs_provenance(
    record: WCSRecord, *, pipeline_version: str = "", input_hashes: tuple[tuple[str, str], ...] = (),
) -> Provenance:
    """`Provenance` real de una solución astrométrica, con los avisos que
    el propio dato obliga a dar.

    `input_hashes`, si se da, debe traer el sha256 real de la imagen que
    se resolvió (p. ej. `io.fits_reader.sha256_file` sobre `ImageView.
    source_path`) -- este módulo no lo calcula ni lo inventa."""
    warnings: list[str] = []
    if not record.is_measured:
        warnings.append(
            "WCS declarado desde la óptica, sin ajuste contra estrellas: "
            "la escala es exacta, pero el centro y la rotación valen lo que valgan los datos introducidos"
        )
    elif record.solution.n_stars < MIN_STARS_FOR_MEANINGFUL_RMS:
        warnings.append(
            f"ajuste con solo {record.solution.n_stars} estrella(s): el RMS declarado "
            f"({record.solution.rms_residual_arcsec:.4f} arcsec) no mide el error real del ajuste, "
            f"hacen falta al menos {MIN_STARS_FOR_MEANINGFUL_RMS}"
        )

    return Provenance.now(
        pipeline_version=pipeline_version,
        engine=record.source,
        engine_version=record.engine_version,
        warnings=tuple(warnings),
        input_hashes=input_hashes,
    )


def wcs_header_cards(record: WCSRecord, *, provenance: Provenance | None = None) -> dict:
    """Tarjetas FITS completas de una solución astrométrica: el WCS
    estándar (CRVAL/CRPIX/CD/CTYPE, vía `astropy`) MÁS la procedencia
    propia con prefijo `APS`.

    `WCSRMS`/`WCSNSTR` se escriben **solo si hay un ajuste real detrás**.
    Una construcción óptica tiene `rms_residual_arcsec = 0.0` y
    `n_stars = 0` justamente para no fingir calidad; volcarlos al archivo
    escribiría `WCSRMS = 0.0`, que cualquier lector interpretaría como un
    ajuste perfecto. En su lugar se escribe `APSWCSMD = F`.
    """
    cards: dict = dict(wcs_solution_to_astropy(record.solution).to_header())
    cards["APSWCS"] = True
    cards["APSWCSRC"] = record.source
    cards["APSWCSVR"] = record.engine_version
    cards["APSWCSMD"] = bool(record.is_measured)
    cards["APSWCSSC"] = round(float(record.pixel_scale_arcsec), 6)

    if record.is_measured:
        cards["WCSRMS"] = round(float(record.solution.rms_residual_arcsec), 6)
        cards["WCSNSTR"] = int(record.solution.n_stars)
    if record.catalog:
        cards["APSWCSCT"] = record.catalog
    if record.n_matched_stars is not None:
        cards["APSWCSNM"] = int(record.n_matched_stars)
    if provenance is not None:
        cards["APSWCSDT"] = provenance.produced_at.isoformat()

    lines = list(record.describe())
    if provenance is not None:
        lines.extend(f"! {w}" for w in provenance.warnings)
        # sha256 real de la imagen resuelta (informes 52/53/54: mismo
        # hueco de `input_hashes` sin rellenar en Provenance).
        for label, digest in provenance.input_hashes:
            lines.append(f"# entrada: {label}")
            lines.append(digest)
    cards["HISTORY"] = wrap_history_lines(lines, prefix=_HISTORY_PREFIX)
    return cards
