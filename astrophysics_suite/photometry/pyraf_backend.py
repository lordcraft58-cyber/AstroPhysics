"""Motor de fotometría alternativo sobre IRAF/PyRAF real -- misma
política que `astrophysics_suite.reduction.pyraf_backend` (ver
docs/audit/33-PYRAF-IRAF-REAL.md): backend aditivo, nunca sustituye al
motor propio (`aperture.py`/`psf.py`, numpy/scipy/photutils, probado de
extremo a extremo y el único cableado en la GUI), requiere una
instalación real de IRAF (sin distribución nativa de Windows; WSL2 +
astroconda es la vía real), y falla explícitamente con
`PyrafUnavailableError` si no está disponible -- nunca en silencio.

**Advertencia honesta sobre verificación**: igual que el backend de
reducción, este módulo se escribió sin poder ejecutar pyraf contra una
instalación real de IRAF en este entorno de desarrollo (mismo bloqueo
de red confirmado hacia `ssb.stsci.edu`/astroconda). Las llamadas a
`phot`/`daofind`/`pstselect`/`psf`/`allstar` de más abajo siguen la
sintaxis real y documentada de los paquetes `digiphot.apphot` y
`digiphot.daophot`, pero NO se han podido ejecutar ni verificar de
extremo a extremo en este entorno. No se marca como "funciona" en
ningún sitio -- antes de confiar en sus resultados hace falta
validación real contra una instalación real de IRAF (ver
`check_pyraf_environment()`).

No está cableado en la GUI por el mismo motivo: `PhotometryDialog` y el
resto de la interfaz siguen usando exclusivamente `photometry/aperture.py`
y `photometry/psf.py`.
"""
from __future__ import annotations

from pathlib import Path

try:
    from pyraf import iraf  # type: ignore[import-not-found]
    from pyraf.iraf import digiphot, apphot, daophot  # noqa: F401 -- carga digiphot.apphot.* y digiphot.daophot.*

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
            "nativa de Windows). Usa el motor propio (astrophysics_suite.photometry.aperture/psf, siempre "
            "disponible) o instala IRAF/PyRAF para activar este backend. "
            f"Error de importación original: {_IMPORT_ERROR!r}"
        )


def check_pyraf_environment() -> tuple[bool, str]:
    """Mismo contrato que `reduction.pyraf_backend.check_pyraf_environment`
    -- diagnóstico honesto antes de intentar una fotometría real."""
    if not HAS_PYRAF:
        return False, f"El paquete pyraf no se pudo importar: {_IMPORT_ERROR!r}"
    try:
        iraf.digiphot.apphot.phot.unlearn()
        iraf.digiphot.daophot.psf.unlearn()
    except Exception as exc:
        return False, (
            f"pyraf se importó pero no se pudo comunicar con una instalación real de IRAF "
            f"(¿faltan los paquetes digiphot.apphot/digiphot.daophot, iraf$, o login.cl?): {type(exc).__name__}: {exc}"
        )
    return True, "IRAF real disponible y respondiendo (digiphot.apphot/digiphot.daophot cargados)."


def _prepare_output(output_path: str) -> Path:
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"{output_path}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otra ruta primero")
    output.parent.mkdir(parents=True, exist_ok=True)
    return output


def run_aperture_photometry_pyraf(
    image_path: str, coords_path: str, output_path: str, *,
    apertures: list[float], annulus: float = 10.0, dannulus: float = 10.0, zmag: float = 25.0,
    fwhmpsf: float = 3.0, sigma: float | None = None, datamin: float | None = None, datamax: float | None = None,
) -> str:
    """Equivalente real de `aperture.measure_aperture_photometry`, pero
    sobre la tarea `phot` real de IRAF/digiphot.apphot -- `coords_path`
    es un archivo real de posiciones (x, y) en formato IRAF (una por
    línea), como el propio `phot` espera."""
    _require_pyraf()
    output = _prepare_output(output_path)

    iraf.digiphot.apphot.phot.unlearn()
    iraf.digiphot.apphot.datapars.fwhmpsf = fwhmpsf
    if sigma is not None:
        iraf.digiphot.apphot.datapars.sigma = sigma
    if datamin is not None:
        iraf.digiphot.apphot.datapars.datamin = datamin
    if datamax is not None:
        iraf.digiphot.apphot.datapars.datamax = datamax
    iraf.digiphot.apphot.fitskypars.annulus = annulus
    iraf.digiphot.apphot.fitskypars.dannulus = dannulus
    iraf.digiphot.apphot.photpars.apertures = ",".join(str(a) for a in apertures)
    iraf.digiphot.apphot.photpars.zmag = zmag
    iraf.digiphot.apphot.phot(
        image=str(image_path), coords=str(coords_path), output=str(output),
        interactive="no", verify="no", Stdout=1,
    )

    if not output.exists():
        raise RuntimeError(f"'phot' no produjo el archivo de salida esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)


def run_daofind_pyraf(
    image_path: str, output_path: str, *,
    fwhmpsf: float = 3.0, sigma: float, threshold: float = 4.0,
    datamin: float | None = None, datamax: float | None = None,
) -> str:
    """Equivalente real de `detection.detect_point_sources`, pero sobre
    la tarea `daofind` real de IRAF/digiphot.apphot -- detección de
    fuentes puntuales vía ajuste de PSF gaussiana real de IRAF, no la
    reimplementación propia con `photutils.DAOStarFinder`."""
    _require_pyraf()
    output = _prepare_output(output_path)

    iraf.digiphot.apphot.daofind.unlearn()
    iraf.digiphot.apphot.datapars.fwhmpsf = fwhmpsf
    iraf.digiphot.apphot.datapars.sigma = sigma
    if datamin is not None:
        iraf.digiphot.apphot.datapars.datamin = datamin
    if datamax is not None:
        iraf.digiphot.apphot.datapars.datamax = datamax
    iraf.digiphot.apphot.findpars.threshold = threshold
    iraf.digiphot.apphot.daofind(image=str(image_path), output=str(output), interactive="no", verify="no", Stdout=1)

    if not output.exists():
        raise RuntimeError(f"'daofind' no produjo el archivo de salida esperado ({output_path}) -- revisa la salida de IRAF para el motivo real.")
    return str(output)


def run_psf_photometry_pyraf(
    image_path: str, coords_path: str, output_dir: str, *,
    fwhmpsf: float = 3.0, sigma: float, datamin: float | None = None, datamax: float | None = None,
    psf_function: str = "gauss",
) -> dict[str, str]:
    """Equivalente real de `psf.fit_empirical_psf` + refinamiento, pero
    encadenando las tareas reales `pstselect` (selección de estrellas
    candidatas a PSF) -> `psf` (construcción del modelo real) ->
    `allstar` (fotometría PSF simultánea real) del paquete
    `digiphot.daophot` -- el flujo real de IRAF para fotometría PSF, en
    tres pasos encadenados sobre archivos reales en disco.

    Devuelve las rutas reales de los tres productos: `{"pst": ...,
    "psf": ..., "allstar": ...}`."""
    _require_pyraf()
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    pst_path = out_dir / "candidates.pst"
    psf_path = out_dir / "model.psf"
    allstar_path = out_dir / "allstar.als"
    for p in (pst_path, psf_path, allstar_path):
        if p.exists():
            raise FileExistsError(f"{p}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otro directorio primero")

    iraf.digiphot.apphot.datapars.fwhmpsf = fwhmpsf
    iraf.digiphot.apphot.datapars.sigma = sigma
    if datamin is not None:
        iraf.digiphot.apphot.datapars.datamin = datamin
    if datamax is not None:
        iraf.digiphot.apphot.datapars.datamax = datamax
    iraf.digiphot.daophot.daopars.function = psf_function

    iraf.digiphot.daophot.pstselect.unlearn()
    iraf.digiphot.daophot.pstselect(image=str(image_path), photfile=str(coords_path), pstfile=str(pst_path), maxnpsf=25, interactive="no", verify="no", Stdout=1)
    if not pst_path.exists():
        raise RuntimeError(f"'pstselect' no produjo el archivo de candidatos esperado ({pst_path}) -- revisa la salida de IRAF para el motivo real.")

    iraf.digiphot.daophot.psf.unlearn()
    iraf.digiphot.daophot.psf(image=str(image_path), photfile=str(coords_path), pstfile=str(pst_path), psfimage=str(psf_path), opstfile=str(out_dir / "candidates.opst"), groupfile=str(out_dir / "candidates.psg"), interactive="no", verify="no", Stdout=1)
    if not psf_path.exists():
        raise RuntimeError(f"'psf' no produjo el modelo de PSF esperado ({psf_path}) -- revisa la salida de IRAF para el motivo real.")

    iraf.digiphot.daophot.allstar.unlearn()
    iraf.digiphot.daophot.allstar(image=str(image_path), photfile=str(coords_path), psfimage=str(psf_path), allstarfile=str(allstar_path), rejfile="", subimage="no", verify="no", Stdout=1)
    if not allstar_path.exists():
        raise RuntimeError(f"'allstar' no produjo el archivo de fotometría esperado ({allstar_path}) -- revisa la salida de IRAF para el motivo real.")

    return {"pst": str(pst_path), "psf": str(psf_path), "allstar": str(allstar_path)}
