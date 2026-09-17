"""Motor de reducción CCD alternativo sobre IRAF/PyRAF real -- pedido
explícito del encargo: reescribir la parte de reducción usando pyraf de
verdad, no una reimplementación propia (que es lo que hace el resto de
`reduction/`, con IRAF como referencia funcional -- ver
docs/audit/33-PYRAF-IRAF-REAL.md para la distinción y el motivo del
cambio de política).

## Requisitos reales (nunca omitidos ni suavizados)

Este módulo necesita una instalación REAL de IRAF (el propio sistema
NOAO, no solo el paquete `pyraf` de Python) accesible en el `PATH`/
`iraf$` del proceso. IRAF no tiene una distribución nativa de Windows;
la única vía real es un entorno Linux -- WSL2 con IRAF instalado vía el
canal astroconda (`http://ssb.stsci.edu/astroconda`) es la ruta
documentada y recomendada. Sin esa instalación, `HAS_PYRAF` es `False`
y CUALQUIER función de este módulo lanza `PyrafUnavailableError`
explícitamente -- nunca cae en silencio al motor propio ni inventa un
resultado.

## Advertencia honesta sobre verificación

Este módulo se escribió sin poder ejecutar pyraf contra una instalación
real de IRAF: el entorno de desarrollo de esta sesión no tiene salida
de red hacia `ssb.stsci.edu` (`host_not_allowed`, confirmado
directamente), y `conda-forge` no distribuye los paquetes `iraf`/
`pyraf` (confirmado consultando su `channeldata.json` real). Las
llamadas a `zerocombine`/`darkcombine`/`flatcombine`/`ccdproc` de más
abajo siguen la sintaxis real y documentada del paquete `ccdred`
(estable, sin cambios sustanciales desde los años 90), pero NO se han
podido ejecutar ni verificar de extremo a extremo en este entorno.
**No se marca como "funciona" en ningún sitio** -- antes de confiar en
sus resultados, hace falta validación real (ver
`check_pyraf_environment()` y el checklist en el documento de auditoría)
contra una instalación real de IRAF.

## Por qué no está cableado todavía en la GUI

Por la misma razón: el motor propio (`combine.py`/`master_frames.py`,
numpy/scipy, sí probado de extremo a extremo con datos reales) sigue
siendo el único camino que usa `BuildMasterFrameDialog`. Cablear este
backend en la interfaz antes de poder verificarlo de verdad violaría
la regla central del encargo (nunca marcar como funcionando algo no
validado) -- queda como el siguiente paso, una vez haya una instalación
real de IRAF contra la que probar.
"""
from __future__ import annotations

from pathlib import Path

try:
    from pyraf import iraf  # type: ignore[import-not-found]
    from pyraf.iraf import ccdred, imred, noao  # noqa: F401 -- necesario para que `iraf.noao.imred.ccdred.*` quede cargado

    HAS_PYRAF = True
    _IMPORT_ERROR: Exception | None = None
except Exception as exc:  # pragma: no cover -- este entorno nunca tiene pyraf instalado
    iraf = None
    HAS_PYRAF = False
    _IMPORT_ERROR = exc


class PyrafUnavailableError(RuntimeError):
    """PyRAF/IRAF no están instalados o configurados en este entorno.
    Nunca se debe llamar a una función de este módulo sin comprobar
    `HAS_PYRAF` antes -- por eso cada función pública lo comprueba ella
    misma y lanza esto en vez de fallar con un error de importación
    críptico más abajo."""


def _require_pyraf() -> None:
    if not HAS_PYRAF:
        raise PyrafUnavailableError(
            "PyRAF/IRAF no están disponibles en este entorno -- requieren una instalación real de IRAF "
            "(p. ej. bajo WSL2 + astroconda: http://ssb.stsci.edu/astroconda; no existe una distribución "
            "nativa de Windows). Usa el motor propio (astrophysics_suite.reduction.master_frames, siempre "
            "disponible) o instala IRAF/PyRAF para activar este backend. "
            f"Error de importación original: {_IMPORT_ERROR!r}"
        )


def check_pyraf_environment() -> tuple[bool, str]:
    """Diagnóstico real -- pensado para que el usuario compruebe su
    propia instalación ANTES de intentar una reducción real, con un
    mensaje accionable en vez de un fallo a mitad de una combinación.

    Devuelve `(ok, detalle)`. `ok=False` cubre tanto "pyraf no está
    instalado" como "pyraf está instalado pero IRAF no responde" (p.
    ej. `iraf$` sin definir, o sin `login.cl`) -- casos reales y
    distintos que un usuario necesita poder diferenciar."""
    if not HAS_PYRAF:
        return False, f"El paquete pyraf no se pudo importar: {_IMPORT_ERROR!r}"
    try:
        version = iraf.envget("version") if hasattr(iraf, "envget") else None
        iraf.noao.imred.ccdred.zerocombine.unlearn()
    except Exception as exc:  # nunca se oculta -- se informa el motivo real
        return False, (
            f"pyraf se importó pero no se pudo comunicar con una instalación real de IRAF "
            f"(¿falta iraf$, login.cl, o el propio IRAF no está instalado?): {type(exc).__name__}: {exc}"
        )
    return True, f"IRAF real disponible y respondiendo (versión: {version or 'desconocida'})."


def _run_combine_task(task, input_paths: list[str], output_path: str, *, kind: str, **task_kwargs) -> None:
    _require_pyraf()
    if len(input_paths) < 3:
        raise ValueError(f"combinar {kind} con IRAF necesita al menos 3 fotogramas; recibidos {len(input_paths)}")
    output = Path(output_path)
    if output.exists():
        raise FileExistsError(f"{output_path}: ya existe -- IRAF nunca sobrescribe en silencio; elimínalo o elige otra ruta primero")
    output.parent.mkdir(parents=True, exist_ok=True)

    task.unlearn()
    input_list = ",".join(str(p) for p in input_paths)
    task(input=input_list, output=str(output), Stdout=1, **task_kwargs)

    if not output.exists():
        # IRAF suele añadir la extensión .fits si el nombre no la trae -- se
        # comprueba también esa variante antes de dar el fallo por bueno.
        if not output.with_suffix(".fits").exists():
            raise RuntimeError(
                f"la tarea IRAF '{task.getName() if hasattr(task, 'getName') else kind}' no produjo el archivo de "
                f"salida esperado ({output_path}) -- revisa la salida de IRAF para el motivo real."
            )


def combine_bias_frames_pyraf(
    input_paths: list[str], output_path: str, *, combine: str = "average", reject: str = "minmax",
) -> None:
    """Equivalente real de `master_frames.build_master_bias`, pero sobre
    la tarea `zerocombine` real de IRAF/ccdred -- opera sobre archivos
    FITS reales en disco (como el propio IRAF), no sobre arrays en
    memoria."""
    _require_pyraf()  # antes de tocar `iraf.noao...` -- si no, el AttributeError sobre None tapa el error accionable
    _run_combine_task(
        iraf.noao.imred.ccdred.zerocombine, input_paths, output_path, kind="bias",
        combine=combine, reject=reject, ccdtype="", process="no", scale="none",
    )


def combine_dark_frames_pyraf(
    input_paths: list[str], output_path: str, *, exposure_s: float, combine: str = "average", reject: str = "minmax",
) -> None:
    """Equivalente real de `master_frames.build_master_dark` vía
    `darkcombine` -- `exposure_s` se registra en la cabecera de salida
    (mismo campo `EXPTIME` que ya usa el motor propio) para que
    `ccdproc` pueda escalar la corriente de oscuridad más adelante."""
    _require_pyraf()
    _run_combine_task(
        iraf.noao.imred.ccdred.darkcombine, input_paths, output_path, kind="dark",
        combine=combine, reject=reject, ccdtype="", process="no", scale="exposure",
    )
    iraf.hedit(images=str(output_path), fields="EXPTIME", value=str(float(exposure_s)), add="yes", verify="no", show="no")


def combine_flat_frames_pyraf(
    input_paths: list[str], output_path: str, *, combine: str = "average", reject: str = "avsigclip",
) -> None:
    """Equivalente real de `master_frames.build_master_flat` vía
    `flatcombine` -- IRAF normaliza a la moda por defecto (`scale=
    "mode"`), a diferencia del motor propio (mediana 1.0); ambos son
    normalizaciones válidas, pero no producen bit a bit el mismo
    resultado -- documentado aquí para que no sorprenda al comparar."""
    _require_pyraf()
    _run_combine_task(
        iraf.noao.imred.ccdred.flatcombine, input_paths, output_path, kind="flat",
        combine=combine, reject=reject, ccdtype="", subsets="no", process="no", scale="mode",
    )


def apply_calibration_pyraf(
    input_paths: list[str], output_dir: str, *,
    master_bias_path: str | None = None, master_dark_path: str | None = None, master_flat_path: str | None = None,
) -> list[str]:
    """Equivalente real de `calibration.apply_calibration` vía
    `ccdproc` -- aplica bias/dark/flat (los que se den) a cada imagen de
    `input_paths`, escribiendo una copia calibrada por cada una en
    `output_dir`. Devuelve las rutas de salida reales, ya escritas a
    disco (nunca solo en memoria, coherente con cómo opera IRAF)."""
    _require_pyraf()
    if not input_paths:
        raise ValueError("apply_calibration_pyraf necesita al menos una imagen de entrada")
    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    output_paths = [str(out_dir / Path(p).name) for p in input_paths]

    iraf.noao.imred.ccdred.ccdproc.unlearn()
    iraf.noao.imred.ccdred.ccdproc(
        images=",".join(input_paths),
        output=",".join(output_paths),
        ccdtype="",
        fixpix="no", overscan="no", trim="no",
        zerocor="yes" if master_bias_path else "no",
        darkcor="yes" if master_dark_path else "no",
        flatcor="yes" if master_flat_path else "no",
        zero=master_bias_path or "",
        dark=master_dark_path or "",
        flat=master_flat_path or "",
        Stdout=1,
    )
    missing = [p for p in output_paths if not Path(p).exists()]
    if missing:
        raise RuntimeError(f"ccdproc no produjo {len(missing)} de {len(output_paths)} archivo(s) de salida esperados: {missing}")
    return output_paths
