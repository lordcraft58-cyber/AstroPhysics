"""Motor de astrometría alternativo sobre IRAF/PyRAF real -- misma
política que `astrophysics_suite.reduction.pyraf_backend` (ver
docs/audit/33-PYRAF-IRAF-REAL.md): backend aditivo, nunca sustituye al
motor propio (`wcs_fit.py`/`registration.py`, astropy/reproject, probado
de extremo a extremo y el único cableado en la GUI), requiere una
instalación real de IRAF (sin distribución nativa de Windows; WSL2 +
astroconda es la vía real), y falla explícitamente con
`PyrafUnavailableError` si no está disponible -- nunca en silencio.

**Advertencia honesta sobre verificación**: igual que los otros
backends pyraf de este proyecto, este módulo se escribió sin poder
ejecutar pyraf contra una instalación real de IRAF en este entorno de
desarrollo (mismo bloqueo de red confirmado hacia `ssb.stsci.edu`/
astroconda). Las llamadas a `ccmap`/`wregister` de más abajo siguen la
sintaxis real y documentada de los paquetes `images.imcoords` e
`images.immatch`, pero NO se han podido ejecutar ni verificar de
extremo a extremo en este entorno. No se marca como "funciona" en
ningún sitio -- antes de confiar en sus resultados hace falta
validación real contra una instalación real de IRAF (ver
`check_pyraf_environment()`).

No está cableado en la GUI por el mismo motivo: `WcsFitDialog` y
`RegisterByWcsDialog` siguen usando exclusivamente `astrometry/wcs_fit.py`
y `astrometry/registration.py`.
"""
from __future__ import annotations

from pathlib import Path

try:
    from pyraf import iraf  # type: ignore[import-not-found]
    from pyraf.iraf import images, imcoords, immatch  # noqa: F401 -- carga images.imcoords.* e images.immatch.*

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
            "nativa de Windows). Usa el motor propio (astrophysics_suite.astrometry.wcs_fit/registration, "
            f"siempre disponible) o instala IRAF/PyRAF para activar este backend. Error de importación original: {_IMPORT_ERROR!r}"
        )


def check_pyraf_environment() -> tuple[bool, str]:
    """Mismo contrato que los demás backends pyraf del proyecto --
    diagnóstico honesto antes de intentar un ajuste de WCS real."""
    if not HAS_PYRAF:
        return False, f"El paquete pyraf no se pudo importar: {_IMPORT_ERROR!r}"
    try:
        iraf.images.imcoords.ccmap.unlearn()
        iraf.images.immatch.wregister.unlearn()
    except Exception as exc:
        return False, (
            f"pyraf se importó pero no se pudo comunicar con una instalación real de IRAF "
            f"(¿faltan los paquetes images.imcoords/images.immatch, iraf$, o login.cl?): {type(exc).__name__}: {exc}"
        )
    return True, "IRAF real disponible y respondiendo (images.imcoords/images.immatch cargados)."


def fit_wcs_pyraf(
    matches_path: str, database_path: str, *,
    image_path: str | None = None, lngunits: str = "degrees", latunits: str = "degrees",
    fitgeometry: str = "general",
) -> str:
    """Equivalente real de `wcs_fit.fit_wcs`, pero sobre la tarea `ccmap`
    real de IRAF/images.imcoords -- `matches_path` es un archivo real de
    correspondencias (columnas x y ra dec, ya calculadas -- p. ej. por
    el propio motor de crossmatch contra Gaia usado en el resto del
    proyecto) que `ccmap` ajusta para producir la solución de WCS real.
    Si se da `image_path`, escribe el WCS ajustado directamente en su
    cabecera (`update="yes"`), como hace IRAF de verdad; si no, solo
    escribe la solución en `database_path` sin tocar ninguna imagen."""
    _require_pyraf()
    database = Path(database_path)
    if database.exists():
        raise FileExistsError(f"{database_path}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otra ruta primero")
    database.parent.mkdir(parents=True, exist_ok=True)

    iraf.images.imcoords.ccmap.unlearn()
    iraf.images.imcoords.ccmap(
        input=str(matches_path), database=str(database),
        images=str(image_path) if image_path else "",
        xcolumn=1, ycolumn=2, lngcolumn=3, latcolumn=4,
        lngunits=lngunits, latunits=latunits, insystem="j2000",
        fitgeometry=fitgeometry, function="polynomial", xxorder=2, xyorder=2, yxorder=2, yyorder=2,
        update="yes" if image_path else "no", interactive="no", verbose="no", Stdout=1,
    )

    if not database.exists():
        raise RuntimeError(f"'ccmap' no produjo la base de datos de solución esperada ({database_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(database)


def register_images_pyraf(reference_path: str, input_paths: list[str], output_dir: str) -> list[str]:
    """Equivalente real de `registration.reproject_to_reference`, pero
    sobre la tarea `wregister` real de IRAF/images.immatch -- reproyecta
    cada imagen de `input_paths` al sistema de coordenadas (WCS) real ya
    presente en la cabecera de `reference_path`. Requiere que todas las
    imágenes de entrada ya tengan un WCS válido en su cabecera (p. ej.
    escrito por `fit_wcs_pyraf` o por el motor propio)."""
    _require_pyraf()
    if not input_paths:
        raise ValueError("register_images_pyraf necesita al menos una imagen de entrada")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [str(out_dir / Path(p).name) for p in input_paths]
    for p in output_paths:
        if Path(p).exists():
            raise FileExistsError(f"{p}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otro directorio primero")

    iraf.images.immatch.wregister.unlearn()
    iraf.images.immatch.wregister(
        input=",".join(input_paths), reference=str(reference_path), output=",".join(output_paths),
        fluxconserve="no", Stdout=1,
    )

    missing = [p for p in output_paths if not Path(p).exists()]
    if missing:
        raise RuntimeError(f"'wregister' no produjo {len(missing)} de {len(output_paths)} archivo(s) de salida esperados: {missing}")
    return output_paths
