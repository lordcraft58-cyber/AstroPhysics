"""Motor de espectroscopía alternativo sobre IRAF/PyRAF real -- misma
política que `astrophysics_suite.reduction.pyraf_backend` (ver
docs/audit/33-PYRAF-IRAF-REAL.md): backend aditivo, nunca sustituye al
motor propio (`trace.py`/`wavelength.py`/`fluxcal.py`/`continuum.py`,
numpy/scipy, probado de extremo a extremo y el único cableado en la
GUI), requiere una instalación real de IRAF (sin distribución nativa de
Windows; WSL2 + astroconda es la vía real), y falla explícitamente con
`PyrafUnavailableError` si no está disponible -- nunca en silencio.

**Advertencia honesta sobre verificación**: igual que los otros
backends pyraf de este proyecto, este módulo se escribió sin poder
ejecutar pyraf contra una instalación real de IRAF en este entorno de
desarrollo (mismo bloqueo de red confirmado hacia `ssb.stsci.edu`/
astroconda). Las llamadas a `apall`/`reidentify`/`dispcor`/`standard`/
`sensfunc`/`calibrate`/`continuum` de más abajo siguen la sintaxis real
y documentada de los paquetes `noao.twodspec.apextract` y
`noao.onedspec`, pero NO se han podido ejecutar ni verificar de extremo
a extremo en este entorno. No se marca como "funciona" en ningún sitio
-- antes de confiar en sus resultados hace falta validación real contra
una instalación real de IRAF (ver `check_pyraf_environment()`).

Nota real sobre `identify`/calibración de longitud de onda: la tarea
`identify` de IRAF es intrínsecamente interactiva (requiere que un
humano marque líneas espectrales conocidas la primera vez). Por eso
`calibrate_wavelength_pyraf()` usa `reidentify`, que SÍ puede correr en
modo no interactivo -- pero necesita una solución de referencia
(`reference_path`) ya identificada de antemano (p. ej. por un `identify`
interactivo previo, fuera del alcance automatizable de este backend).
Esto es una limitación real del propio IRAF, no de este módulo.

No está cableado en la GUI por el mismo motivo que los demás backends:
los diálogos de espectroscopía siguen usando exclusivamente los módulos
propios de `spectroscopy/`.
"""
from __future__ import annotations

from pathlib import Path

try:
    from pyraf import iraf  # type: ignore[import-not-found]
    from pyraf.iraf import noao, twodspec, apextract, onedspec  # noqa: F401 -- carga noao.twodspec.apextract.* y noao.onedspec.*

    HAS_PYRAF = True
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover -- este entorno nunca tiene pyraf instalado
    iraf = None
    HAS_PYRAF = False
    _IMPORT_ERROR = exc


class PyrafUnavailableError(RuntimeError):
    """PyRAF/IRAF no están instalados o configurados en este entorno.
    Cada función pública de este módulo comprueba `HAS_PYRAF` con
    `_require_pyraf()` ANTES de tocar cualquier símbolo real de `iraf`,
    para lanzar esto en vez de un `AttributeError` críptico."""


def _require_pyraf() -> None:
    if not HAS_PYRAF:
        raise PyrafUnavailableError(
            "PyRAF/IRAF no están disponibles en este entorno -- requieren una instalación real de IRAF "
            "(p. ej. bajo WSL2 + astroconda: http://ssb.stsci.edu/astroconda; no existe una distribución "
            "nativa de Windows). Usa el motor propio (astrophysics_suite.spectroscopy.*, siempre disponible) "
            f"o instala IRAF/PyRAF para activar este backend. Error de importación original: {_IMPORT_ERROR!r}"
        )


def check_pyraf_environment() -> tuple[bool, str]:
    """Mismo contrato que los demás backends pyraf del proyecto --
    diagnóstico honesto antes de intentar una reducción espectral real."""
    if not HAS_PYRAF:
        return False, f"El paquete pyraf no se pudo importar: {_IMPORT_ERROR!r}"
    try:
        iraf.noao.twodspec.apextract.apall.unlearn()
        iraf.noao.onedspec.continuum.unlearn()
    except Exception as exc:
        return False, (
            f"pyraf se importó pero no se pudo comunicar con una instalación real de IRAF "
            f"(¿faltan los paquetes noao.twodspec.apextract/noao.onedspec, iraf$, o login.cl?): {type(exc).__name__}: {exc}"
        )
    return True, "IRAF real disponible y respondiendo (noao.twodspec.apextract/noao.onedspec cargados)."


def _prepare_output(output_path: str) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"{output_path}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otra ruta primero")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def extract_spectrum_pyraf(
    image_path: str, output_path: str, *,
    line: int | None = None, nsum: int = 10, lower: float = -5.0, upper: float = 5.0, background: str = "fit",
) -> str:
    """Equivalente real de `trace.trace_spectrum` + extracción, pero
    sobre la tarea `apall` real de IRAF/noao.twodspec.apextract -- IRAF
    hace trazado y extracción en un único paso encadenado (a diferencia
    del motor propio, que los separa en `trace.py`)."""
    _require_pyraf()
    output = _prepare_output(output_path)

    iraf.noao.twodspec.apextract.apall.unlearn()
    iraf.noao.twodspec.apextract.apall(
        input=str(image_path), output=str(output),
        line=line if line is not None else "INDEF", nsum=nsum, lower=lower, upper=upper,
        background=background, interactive="no", find="yes", recenter="yes", resize="no",
        edit="no", trace="yes", fittrace="yes", extract="yes", review="no", Stdout=1,
    )

    if not output.exists():
        raise RuntimeError(f"'apall' no produjo el espectro extraído esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)


def calibrate_wavelength_pyraf(spectrum_path: str, reference_path: str, output_path: str, *, interactive: bool = False) -> str:
    """Equivalente real de `wavelength.calibrate_wavelength`, pero sobre
    las tareas reales `reidentify` + `dispcor` de IRAF/noao.onedspec --
    `reference_path` debe ser un espectro con una solución de longitud
    de onda ya identificada (ver nota del docstring del módulo sobre por
    qué `identify` en sí no es automatizable). `reidentify` reajusta esa
    solución de referencia contra `spectrum_path`, y `dispcor` aplica la
    corrección de dispersión resultante para producir el espectro
    calibrado real en `output_path`."""
    _require_pyraf()
    output = _prepare_output(output_path)

    iraf.noao.onedspec.reidentify.unlearn()
    iraf.noao.onedspec.reidentify(
        reference=str(reference_path), images=str(spectrum_path),
        interactive="yes" if interactive else "no", verbose="no", Stdout=1,
    )

    iraf.noao.onedspec.dispcor.unlearn()
    iraf.noao.onedspec.dispcor(input=str(spectrum_path), output=str(output), linearize="yes", Stdout=1)

    if not output.exists():
        raise RuntimeError(f"'dispcor' no produjo el espectro calibrado esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)


def flux_calibrate_pyraf(
    standard_spectrum_path: str, standard_star_name: str, science_spectrum_path: str, output_path: str, *,
    observatory: str = "", extinction: str = "",
) -> str:
    """Equivalente real de `fluxcal.apply_flux_calibration`, pero
    encadenando las tareas reales `standard` (mide el espectro de una
    estrella estándar) -> `sensfunc` (deriva la función de sensibilidad
    real) -> `calibrate` (aplica esa función a `science_spectrum_path`)
    de IRAF/noao.onedspec."""
    _require_pyraf()
    output = _prepare_output(output_path)
    std_table = Path(output_path).with_suffix(".std")
    sens_path = Path(output_path).with_suffix(".sens")
    for p in (std_table, sens_path):
        if p.exists():
            raise FileExistsError(f"{p}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otra ruta primero")

    iraf.noao.onedspec.standard.unlearn()
    iraf.noao.onedspec.standard(
        input=str(standard_spectrum_path), output=str(std_table), star_name=standard_star_name,
        observatory=observatory, extinction=extinction, interactive="no", Stdout=1,
    )

    iraf.noao.onedspec.sensfunc.unlearn()
    iraf.noao.onedspec.sensfunc(standards=str(std_table), sensitivity=str(sens_path), extinction=extinction, interactive="no", Stdout=1)

    iraf.noao.onedspec.calibrate.unlearn()
    iraf.noao.onedspec.calibrate(
        input=str(science_spectrum_path), output=str(output), sensitivity=str(sens_path),
        extinct="yes" if extinction else "no", extinction=extinction, observatory=observatory, Stdout=1,
    )

    if not output.exists():
        raise RuntimeError(f"'calibrate' no produjo el espectro calibrado en flujo esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)


def fit_continuum_pyraf(spectrum_path: str, output_path: str, *, order: int = 5, function: str = "spline3", low_reject: float = 2.0, high_reject: float = 0.0) -> str:
    """Equivalente real de `continuum.normalize_continuum`, pero sobre
    la tarea `continuum` real de IRAF/noao.onedspec -- ajusta y divide
    (o resta, según `type`) el continuo real, no la reimplementación
    propia con `scipy`."""
    _require_pyraf()
    output = _prepare_output(output_path)

    iraf.noao.onedspec.continuum.unlearn()
    iraf.noao.onedspec.continuum(
        input=str(spectrum_path), output=str(output),
        order=order, function=function, low_reject=low_reject, high_reject=high_reject,
        interactive="no", type="ratio", Stdout=1,
    )

    if not output.exists():
        raise RuntimeError(f"'continuum' no produjo el espectro normalizado esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)
