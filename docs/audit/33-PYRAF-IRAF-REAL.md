# 33 — Backend real de PyRAF/IRAF para reducción CCD

Pedido explícito del usuario: "quiero que actualices / uses las
librerias pyIRAF y astropy para reescribir / reahacer y mejorar toda la
parte de iraf que hemos implementado antes" -- y, tras una aclaración
sobre viabilidad, confirmado literalmente: "Usa pyraf, y me instalo un
sistema de linux en mi windows para poder ejecutarlo", después
reforzado con "reconstruyas pyraf para Windows y lo implementes en el
programa".

Este documento recoge la investigación real de viabilidad, el motivo
del alcance elegido, y el estado honesto de verificación.

## 1. Por qué "reconstruir pyraf para Windows" no es alcanzable

IRAF (el sistema NOAO real, no solo el paquete Python `pyraf` que lo
controla) es ~2 millones de líneas de Fortran/C con dependencias
profundas del entorno Unix (VOS, el sistema de archivos virtual de
IRAF; `cl`, su propio lenguaje de comandos; rutas `iraf$`, `mtlocal$`,
etc. resueltas vía variables de entorno de estilo Unix). NOAO/AURA
nunca produjo una distribución nativa de Windows en sus ~30 años de
desarrollo activo del sistema, ni tampoco existe un port comunitario
real (a diferencia de, p. ej., un simple `.exe` compilado con MinGW).
No es una limitación de esta sesión ni de este sandbox -- es una
limitación real e inherente del propio software. La única vía honesta
para tener IRAF/PyRAF *real* funcionando desde una máquina Windows es
un entorno Linux real: WSL2 con el canal astroconda (histórico
distribuidor de binarios IRAF/PyRAF vía conda), que es justamente lo
que el usuario ya había aceptado instalar.

Por eso el "backend real de pyraf" descrito en este documento consume
IRAF a través de `pyraf`, y está pensado y escrito para ejecutarse bajo
un entorno Linux real (WSL2 + astroconda) -- no hay, ni puede haber, una
versión "para Windows nativo" de este backend.

## 2. Investigación real de viabilidad en este sandbox de desarrollo

Antes de escribir una sola línea del backend, se comprobó de forma
directa y real (no asumida) qué es alcanzable en el entorno de
desarrollo de esta sesión:

- `curl` contra `http://ssb.stsci.edu/astroconda` (el canal conda real
  que distribuye binarios de IRAF) devuelve `403 Forbidden` con cabecera
  `x-deny-reason: host_not_allowed` -- bloqueado por la política de red
  del sandbox, confirmado directamente, no supuesto.
- `conda-forge` (el canal sin restricción de red disponible) fue
  inspeccionado vía su `channeldata.json` real: no distribuye paquetes
  `iraf` ni `pyraf`.
- `pip install pyraf` **sí funciona** en este sandbox (instala pyraf
  2.2.4, que son solo los bindings Python puros que hablan con un IRAF
  ya instalado, no IRAF en sí). Se confirmó con una prueba real en un
  entorno virtual desechable: `from pyraf import iraf` lanza `OSError`
  ("Your \"iraf\" environment variable is not defined...") de forma
  genuina, exactamente el fallo esperado sin una instalación real de
  IRAF detrás.

Conclusión real: no es posible instalar ni ejecutar IRAF/PyRAF de
verdad en este sandbox de desarrollo. El backend se ha escrito con este
límite explícito y sin ocultarlo en ningún sitio.

## 3. Diseño: backend intercambiable, nunca sustituye al motor probado

`astrophysics_suite/reduction/pyraf_backend.py` implementa el
equivalente real de `master_frames.py`/`calibration.py`
(zerocombine/darkcombine/flatcombine/ccdproc reales de IRAF) siguiendo
el mismo patrón de detección de capacidad ya usado en el proyecto para
`HAS_PHOTUTILS`/`HAS_SIMBAD`/`HAS_GAIA`: un `try/except` de importación
que define `HAS_PYRAF`, y cada función pública comprueba esa bandera
ANTES de tocar cualquier símbolo real de `iraf`, lanzando
`PyrafUnavailableError` con un mensaje accionable (qué falta, dónde
conseguirlo) en vez de un `AttributeError` críptico o -- peor -- un
resultado silenciosamente incorrecto.

Es deliberadamente **aditivo**: `BuildMasterFrameDialog` y el resto de
la GUI siguen usando exclusivamente el motor propio numpy/scipy
(`master_frames.py`, probado de extremo a extremo con datos reales
durante todo este proyecto). Cablear el backend pyraf en la interfaz
antes de poder verificarlo de verdad violaría la regla central del
encargo: nunca marcar como funcionando algo no validado. Queda
pendiente para cuando exista una instalación real de IRAF (la del
usuario, vía WSL2) contra la que probar.

## 4. Un bug real encontrado y corregido durante la propia verificación

Al ejecutar por primera vez `tests/unit/reduction/test_pyraf_backend.py`
en este sandbox (donde `HAS_PYRAF` es `False` de verdad), se descubrió
un fallo real de diseño: `combine_bias_frames_pyraf` (y las funciones
de dark/flat) pasaban `iraf.noao.imred.ccdred.zerocombine` como
argumento posicional a `_run_combine_task`. En Python, ese argumento se
evalúa ANTES de entrar en el cuerpo de `_run_combine_task` -- es decir,
antes de que su `_require_pyraf()` interno tuviera oportunidad de
lanzar el error accionable. Con `iraf = None` (el caso real de este
sandbox), esto producía `AttributeError: 'NoneType' object has no
attribute 'noao'` en vez de `PyrafUnavailableError`, justo el tipo de
fallo críptico que el diseño pretendía evitar.

**Corrección real**: cada función pública (`combine_bias_frames_pyraf`,
`combine_dark_frames_pyraf`, `combine_flat_frames_pyraf`) llama ahora a
`_require_pyraf()` explícitamente como primera instrucción, antes de
referenciar cualquier símbolo de `iraf`. Verificado ejecutando de
verdad `test_functions_raise_explicit_error_when_pyraf_unavailable`
tras la corrección: pasa, y el mensaje real capturado coincide con
`PyrafUnavailableError` y no con `AttributeError`.

Este hallazgo es la prueba de por qué las pruebas "honestas sin pyraf"
(sección 5) no son superfluas: corren de verdad en este entorno y ya
han encontrado un bug real antes de que el usuario lo hiciera.

## 5. Estado de verificación (honesto, sin inflar)

`tests/unit/reduction/test_pyraf_backend.py` -- 7 pruebas:

- **2 pruebas corren de verdad en este sandbox y pasan**:
  `test_check_pyraf_environment_reports_real_status` (confirma que
  `check_pyraf_environment()` devuelve `(False, <detalle real>)` en
  este entorno sin IRAF) y
  `test_functions_raise_explicit_error_when_pyraf_unavailable` (confirma
  el mensaje accionable, no un error críptico).
- **5 pruebas se saltan explícitamente** (`@requires_real_pyraf`,
  `skipif(not HAS_PYRAF)`): combinar bias/dark real, registrar
  `EXPTIME`, exigir mínimo de 3 fotogramas, rechazar sobrescritura
  silenciosa, y aplicar calibración real vía `ccdproc`. **Estas 5
  nunca se han ejecutado contra un IRAF real en esta sesión** -- están
  escritas siguiendo la sintaxis real y documentada del paquete
  `ccdred` (estable desde los años 90), pero sin validación de extremo
  a extremo todavía.

Suite completa sin regresiones tras añadir este módulo: `aps-test`
414 passed / 23 skipped / 1 xfailed; `aps-gui` 509 passed / 8 skipped /
1 xfailed.

## 6. Checklist para validar contra IRAF real (WSL2 + astroconda)

Cuando el usuario tenga WSL2 con astroconda/IRAF instalado:

1. `pip install pyraf` dentro de ese entorno Linux (ya con `iraf$` y
   `login.cl` configurados por astroconda).
2. Ejecutar `check_pyraf_environment()` primero -- debe devolver
   `(True, "IRAF real disponible y respondiendo...")`. Si no, el
   detalle indica qué falta (variable de entorno, `login.cl`, etc.)
   antes de intentar nada más.
3. Ejecutar `pytest tests/unit/reduction/test_pyraf_backend.py -v` --
   las 5 pruebas marcadas `@requires_real_pyraf` deben dejar de
   saltarse y pasar de verdad contra archivos FITS reales en disco.
4. Solo después de (3) en verde, considerar cablear este backend como
   alternativa seleccionable en `BuildMasterFrameDialog`/
   `ApplyCalibrationDialog` (pendiente, fuera de esta ronda).

## 7. Alcance de esta ronda: solo reducción CCD

El encargo original pedía reescribir "toda la parte de iraf que hemos
implementado antes", lo cual abarca cuatro subsistemas históricamente
implementados con IRAF como referencia funcional (nunca envuelto):
reducción CCD (`reduction/`), fotometría (`photometry/aperture.py`,
`photometry/psf.py`, PSF con `daophot`), astrometría
(`astrometry/wcs_fit.py`, `astrometry/registration.py`) y
espectroscopía (`spectroscopy/`: trazado, calibración en longitud de
onda, flujo, continuo). Esta ronda cubre únicamente reducción CCD
(`zerocombine`/`darkcombine`/`flatcombine`/`ccdproc`), la base sobre la
que se apoyan los otros tres. Los otros tres subsistemas siguen usando
exclusivamente sus reimplementaciones propias (numpy/scipy/photutils),
sin backend pyraf todavía -- pendiente, no iniciado.
