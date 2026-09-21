# Informe 82 — Espectroscopía slice 27: nombrado estándar + historial de procesamiento (§35/§36/§37/§39)

Continuación del informe 81 (§34, Autoprocesar espectro). Cierra los
cuatro puntos que dependían de que existiera el autoproceso, extendiendo
el único flujo real que ya produce un producto en disco -- "Guardar
espectro calibrado (FITS)..." -- en vez de construir un mecanismo nuevo
de guardado paralelo.

## Diseño

- **§37 (nomenclatura estándar de productos)**:
  `spectrum1d_io.standard_product_name(object_name, source_path, *, kind="1D")`
  -- `Vega_1D.fits` desde el `OBJECT` real de la cabecera FITS, saneado a
  caracteres seguros de nombre de archivo; sin `OBJECT` real, cae al
  nombre base del archivo de origen; sin ninguno de los dos, el marcador
  honesto `espectro_1D.fits` (nunca un nombre de objeto inventado --
  misma disciplina que el marcador "(objeto sin nombre en la cabecera
  FITS)" de §13). Sustituye la convención anterior (`{stem}_1D_
  calibrado.fits`) como nombre por defecto de "Guardar espectro
  calibrado (FITS)...".
- **§36 (historial de procesamiento en JSON)**:
  `astrophysics_suite/spectroscopy/processing_history.py` (nuevo módulo,
  numpy-free): `ProcessingHistoryEntry(timestamp_utc, process_name,
  summary)` + `append_processing_history()`/`load_processing_history()`.
  `ImageView` gana `self.processing_history: list` (§36/§39, ver
  `qt_app/mdi/image_window.py`): `main_window._on_process_finished`
  añade una entrada real por cada proceso que se aplica sobre esa vista
  concreta, en el orden real en que se ejecuta -- no solo el último
  paso de un autoproceso, sino TODA la cadena real de la sesión (traza,
  extracción, calibración, identificación, informe de calidad...).
- **§39 (trazabilidad de cadena completa, nunca sobrescribir en
  silencio)**: al guardar, `spectrum1d_io.processing_history_path_for_
  product()` da la ruta del `.history.json` que acompaña al FITS (p. ej.
  `Vega_1D.fits.history.json`), y `append_processing_history()` funde el
  historial ya guardado en disco (si lo había, de una sesión anterior)
  con las entradas nuevas -- nunca sobrescribe la trazabilidad ya
  registrada. Es idempotente frente a una entrada byte-idéntica ya
  presente (mismo timestamp/proceso/resumen exactos): el llamador real
  (`main_window`) pasa el historial COMPLETO en memoria en cada
  guardado, así que sin deduplicar, guardar el mismo producto una
  segunda vez duplicaría todas las entradas anteriores.
- **§35 (modo manual/reinicio)**: interpretación deliberada, documentada
  aquí en vez de construir una UI de "modo" nueva -- cada proceso del
  taller (incluido "Autoprocesar espectro") ya es libremente rerejecutable
  con parámetros distintos en cualquier momento (nada queda "bloqueado"
  tras un autoproceso), y el historial de procesamiento hace esa cadena
  real VISIBLE en vez de ocultarla: el usuario siempre puede ver qué se
  intentó, con qué resultado, y repetir cualquier paso a mano. No se
  construyó un botón "reiniciar" separado porque no hay ningún estado
  que autoprocesar deje atascado que necesite deshacerse explícitamente.

## Validación

- `ruff check`: limpio en los cinco archivos tocados/nuevos.
- `tests/unit/spectroscopy/test_processing_history.py` (nuevo, 5 tests):
  vacío sin archivo real; escribe y relee entradas reales; acumula
  entre llamadas sin perder las anteriores; idempotente frente al
  historial completo en memoria repasado dos veces; crea directorios
  padre que faltan.
- `tests/unit/spectroscopy/test_spectrum1d_io.py` (+6 tests):
  `standard_product_name` con `OBJECT` real, saneado de caracteres no
  seguros, caída honesta a la ruta de origen sin `OBJECT`, marcador
  honesto sin ninguno de los dos, `kind` distinto; ruta del historial
  junto al producto.
- `tests/gui_smoke/test_qt_app_processing_history_smoke.py` (nuevo, 1
  test): flujo real de calibración por lámpara + guardado -- nombre por
  defecto real `Vega_1D.fits` desde el `OBJECT` de la cabecera, historial
  escrito con la entrada real del guardado, y una segunda llamada al
  mismo guardado ACUMULA (nunca sobrescribe) la cadena.
- Suite unitaria completa: **1055 passed** (antes: 1044).
- Suite de humo GUI completa: **191 passed** (antes: 190) -- sin
  regresiones en `test_qt_app_wavelength_smoke.py` (el guardado
  mockeado de esos tests ignora el nombre por defecto, así que el
  cambio de convención no les afecta).
- Validación real: `standard_product_name` sobre
  `Vega_1sec_1x1__frame6.fit` real produce exactamente `Vega_1D.fits`
  desde el `OBJECT` real de su cabecera (`Vega`); `append_processing_
  history`/`load_processing_history` escriben y releen un historial
  real en disco con las entradas reales de una traza+calibración de ese
  mismo archivo.

## Qué queda del informe 71

De los puntos restantes del informe 71: §2 (edición interactiva de
traza/apertura/cielo), §25 (comparación con plantilla), §33 (generador
sintético público reutilizable) y §43 (test de integración con nombre
propio, extremo a extremo) siguen sin empezar -- ninguno depende ya de
otro, cada uno es su propio slice independiente. §1/§7/§11/§14/§18/§26
son verificaciones/auditorías menores, de menor prioridad.
