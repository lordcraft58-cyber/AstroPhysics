# 31 — Resolución de puntero por nombre de objeto (SIMBAD), estilo SPCC

## 1. Problema real reportado

Tras la Fase 22 (plate solving automático integrado en Discovery), el
usuario reportó en uso real: "sigue sin hacer plate solve". Causa
probable identificada: `solve_plate` solo obtenía el puntero aproximado
del header FITS (`OBJCTRA`/`OBJCTDEC` o `RA`/`DEC`) -- y con software de
captura real (N.I.N.A., SGP, APT, etc.), esas claves a menudo faltan o
usan nombres distintos, aunque el usuario sepa perfectamente qué objeto
está fotografiando (lo escribe al crear la observación en Discovery, o
está en el nombre del archivo/`OBJECT`). Pedido explícitamente: igual
que "Spectrophotometric Color Calibration" de PixInsight -- escribir el
nombre del objeto, resolver contra SIMBAD, usar eso para el plate
solving.

## 2. Cambios

### 2.1 `astrophysics_suite/catalogs/simbad.py` (nuevo)

`resolve_object_coordinates(name) -> (ra_deg, dec_deg, fuente) | None`.
Reutiliza `resolve_object_center` -- ya existente en el código heredado,
con su propia tabla de alias conservadora para objetos Messier/NGC
habituales (M31, M42, M27, NGC6960...) y manejo de errores ya probado
(nunca lanza; cualquier fallo de red/servicio/nombre no resuelto es
`None`, nunca coordenadas inventadas) -- mismo patrón de esta migración
que `catalogs/gaia.py` con `crossmatch_gaia_safe`.

### 2.2 Integrado en Discovery automático

`astrophysics_suite/discovery/pipeline.py`, `_ensure_wcs`: nueva función
`_resolve_approx_pointing(header, target_name)` -- primero el header
FITS (como antes); si no resuelve, SIMBAD usando el **nombre del
objetivo de la observación** (`Observation.target_name`, el mismo que
el usuario escribió en "Nueva observación", sin ningún campo nuevo que
rellenar). El puntero resuelto (de cualquiera de las dos fuentes) se
pasa explícitamente a `solve_plate`. El mensaje de progreso y el
`ImageWCSStatus.detail` final indican de qué fuente vino el puntero
("puntero: header FITS" / "puntero: SIMBAD: M 31"), y si ninguna de las
dos resuelve, el motivo del fallo lo dice explícitamente ("ni en el
header FITS ni resolviendo por SIMBAD... comprueba que el nombre de la
observación sea un objeto real reconocible").

### 2.3 Diálogo "Resolver placa automáticamente..."

`qt_app/astrometry/plate_solve_dialog.py`: nuevo campo "Nombre real del
objeto" (pre-rellenado desde `OBJECT` del header si está) + botón
"Buscar en SIMBAD...", que resuelve en un hilo de fondo y rellena
RA/Dec si tiene éxito, o muestra un mensaje honesto (no toca RA/Dec) si
SIMBAD no resuelve el nombre.

## 3. Verificación real (no solo mocks aislados)

- Unit (`test_simbad.py`, 5 tests): éxito real, nombre vacío, SIMBAD sin
  resultado, fallo de red simulado (nunca lanza), y que de verdad prueba
  los alias Messier heredados (consulta con "m31" en minúsculas,
  confirma que se reintenta con "M 31").
- Integración (`test_generic_discovery_pipeline.py`, +1): FITS real SIN
  ningún puntero en el header (solo `PIXSCALE`), `Observation.target_name
  ="M 31"`, SIMBAD mockeado devolviendo las coordenadas reales de M 31
  -- Discovery resuelve el WCS y llega a candidatos KNOWN reales, no se
  queda en DISCOVERY_REVIEW.
- GUI (`test_qt_app_plate_solve_smoke.py`, +3): botón "Buscar en
  SIMBAD..." rellena RA/Dec reales; reporta honestamente cuando SIMBAD
  no resuelve (sin tocar RA/Dec); el nombre se pre-rellena desde
  `OBJECT` del header.
- Red real (`test_simbad_network.py`, nuevo, mismo patrón honesto que
  `test_gaia_network.py`): intenta una consulta real a SIMBAD por "M 31"
  y se salta explícitamente si no hay conectividad real -- en este
  sandbox de desarrollo, **se salta** (mismo bloqueo de red de salida ya
  documentado para Gaia; no se pudo verificar contra el servicio SIMBAD
  real desde aquí).

Suite completa sin regresiones (aps-test: 408 passed/4 skipped; aps-gui:
505 passed/3 skipped/1 xfailed).

## 4. Límite real que queda

SIMBAD da posición, nunca escala de píxel -- si el header tampoco trae
`PIXSCALE`/`SECPIX`/`FOCALLEN`+`XPIXSZ`, `solve_plate` sigue fallando
honestamente por falta de escala (no hay ninguna fuente externa de
"arcsec/píxel" análoga a SIMBAD). Esto no es un defecto de esta
corrección, es una limitación real del problema: la escala depende del
instrumento, no del objeto.
