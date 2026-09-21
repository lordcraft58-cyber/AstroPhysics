# 90 — Auditoría sistemática, motor 2/16: Reduction

Segundo motor de la fase de cierre sistemático. Reduction ya se había
cerrado formalmente en fases anteriores (10.1/10.2), así que esta
auditoría re-verifica ese cierre contra el checklist de 20 puntos de la
fase actual en vez de darlo por bueno -- y encontró un hueco real: el
único de los tres flujos de calibración de la GUI que nunca escribía su
resultado a disco. Se cierra aquí.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/reduction/{combine,calibration,
overscan,bad_pixel_mask,fringe,sky,frame_classification,illumination,
master_frames,provenance,session_pipeline,pyraf_backend}.py`.
**GUI**: `qt_app/reduction/{apply_calibration_dialog,build_master_frame_dialog,
reduce_session_dialog,master_frame_library}.py`, cuatro entradas reales en
el menú "Reducción" de `main_window.py` (construir maestro, cargar
maestro, aplicar calibración, reducir sesión) -- ninguna huérfana, las
cuatro conectadas a un backend real.
**Registro de procesos genérico**: solo `reduction.overscan` vive ahí
(`qt_app/processes/registry.py`); bias/dark/flat y la aplicación de
calibración usan diálogos dedicados a propósito (necesitan varios
fotogramas de entrada y estado propio -- no encajan en "un proceso
transforma la imagen activa"), decisión ya documentada en el propio
código, no un hueco.
**Tests (antes de este informe)**: `tests/unit/reduction/` -- 12 archivos,
86 tests (bad_pixel_mask=8, calibration=6, combine=7,
frame_classification=4, fringe=5, illumination=4, master_frames=12,
overscan=4, reduction_provenance=11, reduction_pyraf_backend=7,
session_pipeline=13, sky=5). GUI: `tests/gui_smoke/
test_qt_app_reduction_smoke.py` (7 tests), `test_qt_app_reduce_session_smoke.py`.

Se leyó cada archivo del motor completo (no solo se re-ejecutaron los
tests existentes) y se verificó con `grep` que las seis capacidades del
motor científico que en algún momento parecían candidatas a quedar sin
consumidor (`combine`, `fringe`, `illumination`, `overscan`, `sky`,
`bad_pixel_mask`, `frame_classification`) están todas importadas de verdad
por `session_pipeline.py` y/o `reduce_session_dialog.py` -- ninguna vive
solo en su propio test.

## Hallazgo y cierre

### "Aplicar calibración..." nunca ofrecía guardar su resultado

De los tres flujos reales de calibración de la GUI, dos ya escribían a
disco desde su primera versión: "Construir fotograma maestro..."
(`BuildMasterFrameDialog`, obligatorio desde el diseño) y "Reducir sesión
de LIGHTS..." (`ReduceSessionDialog`, informe 10.1). El tercero, "Aplicar
calibración a la imagen activa...", calibraba de verdad
(`calibration.calibrate_frame`, con incertidumbre propagada) pero
`main_window._on_calibration_applied` solo abría una ventana MDI nueva
con el resultado -- si se cerraba esa ventana o la sesión, el trabajo se
perdía sin ninguna forma de recuperarlo. Un resultado científico real
viviendo solo en memoria es justo lo que la fase actual pide cerrar.

Además, `ApplyCalibrationDialog.calibrated` solo emitía `(datos, resumen)`
-- ni la incertidumbre propagada por `calibrate_frame` ni qué pasos
(`CalibrationSteps`) se habían aplicado llegaban al llamador, así que no
había con qué construir procedencia real aunque se quisiera guardar.

**Corregido**, reutilizando exactamente el patrón ya validado en
`ReduceSessionDialog`/`_offer_to_save_wcs_fits_copy`:

- `ApplyCalibrationDialog` ahora emite un `CalibrationOutcome` real
  (`image: UncertainImage` con incertidumbre, `summary`, `record:
  ReductionRecord`, `master_input_hashes` -- sha256 reales de los
  maestros usados, solo de los que ya estaban guardados a disco, mismo
  criterio honesto que `ReduceSessionDialog._on_run`).
- `main_window._on_calibration_applied` sigue abriendo la ventana MDI
  (nada roto) y además llama a `_offer_to_save_calibrated_fits`: construye
  la procedencia real con `build_reduction_provenance`/
  `reduction_header_cards` (las mismas que ya usa la reducción por
  sesión), añade el sha256 real de la imagen de origen solo si
  `view.source_path` sigue apuntando a un archivo real (degradación
  honesta si se movió/borró, igual que el guardado de WCS), pregunta con
  `QMessageBox`, y guarda con `QFileDialog.getSaveFileName` +
  `save_fits_image`.

Tres tests nuevos en `tests/gui_smoke/test_qt_app_reduction_smoke.py`
(además de actualizar los dos existentes que usaban la firma antigua de
la señal): sha256 real cuando el origen existe, degradación honesta
cuando no, y que rechazar la pregunta no escribe nada.

## Validación con datos reales

Script de validación (no un test sintético) contra el LIGHT real de M31
del usuario (`Light_M31_300s_0001.fit`, 3008x3008, uint16 con
BZERO/BSCALE, ASI533MC Pro real -- el mismo tipo de archivo cuyo manejo
de memmap se verificó en el motor de IO/FITS): se cargó con `load_image`,
se calibró contra un bias sintético de la misma forma real, se construyó
la procedencia con el sha256 real del archivo de origen, se guardó a un
FITS real y se recargó -- la cabecera cruda conserva `APSRED`/`APSBIAS`
y el sha256 real completo (64 caracteres, sin cortar) en `HISTORY`, y los
datos calibrados sobreviven guardar+recargar sin cambios. Confirma que el
fix funciona sobre datos reales de forma/tipo real, no solo sobre arrays
sintéticos de prueba.

## Qué queda fuera, documentado (no bloquea el cierre)

- **PyRAF/IRAF** (`pyraf_backend.py`): backend estrictamente opcional,
  correctamente documentado como no verificable en este entorno (sin red
  para instalar IRAF), nunca conectado a la GUI. Exactamente el
  tratamiento que pide la fase actual para esta capacidad -- no se toca.
- **Los resultados del registro de procesos genérico no se pueden
  guardar a disco**: `reduction.overscan` (y cualquier otro proceso del
  taller -- `imtools.debayer`, `imtools.crop`, etc.) siempre termina en
  `main_window._on_process_finished` abriendo una ventana MDI nueva, sin
  ninguna opción de guardar. Es un patrón real, pero es **de todo el
  taller de procesos genéricos**, no específico de Reduction -- tocarlo
  significaría construir una capacidad nueva ("Guardar imagen activa
  como...") que afecta a motores fuera de este, lo que esta fase prohíbe
  explícitamente. Los tres flujos que SÍ son productos terminales reales
  de Reduction (fotogramas maestros, sesión reducida, calibración de una
  imagen) ya escriben a disco los tres tras este informe; overscan por sí
  solo, aplicado fuera de esos flujos, es una vista previa/utilidad, no
  un producto de Reduction. Queda anotado para una eventual fase futura
  centrada en el taller de procesos genérico, no en un motor científico
  concreto.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- overscan/bias/dark/flat/iluminación/franjas/cielo/máscara de píxeles, todo propio, sin legacy |
| Entrada definida | Sí -- arrays ya cargados (nunca releídos dentro del motor) + parámetros físicos tipados |
| Salida definida | Sí -- `UncertainImage`/`MasterFrame`/`CombineResult`/`ReductionSessionResult`/`CalibrationOutcome` |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- e-/ADU, segundos de exposición, sigma robusta consistente en todo el motor |
| Incertidumbres cuando correspondan | Sí -- propagada de principio a fin (`UncertainImage`), nunca perdida al guardar (`UNCERT`/incertidumbre en el FITS calibrado) |
| Manejo explícito de datos faltantes | Sí -- `EXPTIME` ausente con dark lanza error explícito, nunca asume un valor |
| NOT_AVAILABLE cuando proceda | Sí -- hash de un maestro no guardado a disco se omite, nunca se inventa |
| Provenance | Sí -- `ReductionRecord`/`build_reduction_provenance`/`reduction_header_cards` en los TRES flujos de guardado (antes solo en dos) |
| Errores correctamente gestionados | Sí -- `ValueError` específicos en cada validación física, capturados y mostrados en la GUI |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/reduction/` |
| Conectado al motor anterior (IO/FITS) | Sí -- consume `LoadedImage`/`ImageRef` tal cual los entrega el motor 1 |
| Conectado al siguiente (Astrometry/WCS) | Sí -- el FITS calibrado guardado (con o sin recorte) es la entrada estándar del siguiente motor; el recorte invalida el WCS de origen y se elimina explícitamente (`strip_wcs_keywords`) en vez de arrastrarlo mintiendo |
| GUI funcional | Sí -- cuatro entradas de menú reales, las cuatro conectadas a un backend real, ninguna huérfana |
| Guardado de resultados correcto | Sí -- los TRES flujos de calibración escriben a disco tras este informe (antes solo dos) |
| Rutas de salida controladas por el usuario | Sí -- `QFileDialog` nativo en los tres flujos |
| Tests unitarios | Sí -- 86 (sin cambios; el fix es de capa GUI) |
| Tests de integración | Sí -- consumido end-to-end por Astrometría/Detección (motores posteriores) |
| Test de regresión | N/A directo (no hay lector legacy de reducción que comparar); cubierto por el resto de la suite (1688 passed) |
| Validación con datos reales/controlados | Sí -- LIGHT real de M31 (3008x3008, uint16 BZERO/BSCALE), ver arriba |
| Documentación actualizada | Sí -- este informe + comentarios nuevos en el código explicando el hallazgo |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

- `ruff check astrophysics_suite qt_app tests`: limpio.
- Unitaria + integración + regresión: **1688 passed**, 24 skipped (sin
  regresión respecto al informe 89).
- Humo GUI completa: **212 passed** (antes: 209 -- los 3 tests nuevos de
  este informe).

## CHECKPOINT

```
MOTOR: Reduction
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/reduction/{combine,calibration,overscan,bad_pixel_mask,fringe,sky,frame_classification,illumination,master_frames,provenance,session_pipeline}.py
ENTRADA: arrays ya cargados (ImageRef/LoadedImage del motor 1) + parámetros físicos (gain, read_noise, exposición, regiones)
SALIDA: UncertainImage / MasterFrame / ReductionSessionResult / CalibrationOutcome, todos con incertidumbre y procedencia real
GUI: sí (4 entradas de menú: construir maestro, cargar maestro, aplicar calibración, reducir sesión -- las 4 conectadas a un backend real)
PROVENANCE: sí (ReductionRecord + build_reduction_provenance + reduction_header_cards, ahora en los 3 flujos que guardan a disco)
TESTS: 86 unitarios + 10 humo GUI de reducción (7 previos + 3 nuevos) = 96 tests directamente del motor
TESTS PASADOS: 96 (1688 unit/integración/regresión + 212 humo GUI en conjunto, sin fallos)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (LIGHT real de M31, 3008x3008 uint16 BZERO/BSCALE, ASI533MC Pro real -- calibración + procedencia + guardado + recarga verificados byte a byte)
PROBLEMAS RESTANTES: ninguno bloqueante. Documentados y fuera de alcance: PyRAF/IRAF sigue LIMITADO (correcto, no verificable en este entorno); los resultados del registro de procesos genérico (overscan incluido) no se pueden guardar a disco -- gap real pero de todo el taller de procesos, no específico de Reduction, fuera de alcance de este motor.
CONTRATO HACIA EL SIGUIENTE MOTOR (Astrometry/WCS): un FITS calibrado real en disco (con incertidumbre y cabecera de procedencia APS*), con el WCS de origen eliminado explícitamente si hubo recorte -- exactamente lo que astrometry/provenance.py y los diálogos de WCS ya esperan como entrada hoy.
```

## Cambio de motor

Reduction re-auditado y cerrado bajo el checklist de 20 puntos, con un
hallazgo real corregido, testeado y validado con datos reales. Siguiente
en el orden fijo del usuario: **Astrometry/WCS**.
