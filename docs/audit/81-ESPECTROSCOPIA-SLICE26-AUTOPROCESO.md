# Informe 81 — Espectroscopía slice 26: Autoprocesar espectro (§34)

Continuación del informe 80. Cierra el hueco real más grande que quedaba
del informe 71: un único botón que encadena, sobre un espectro estelar
ya reducido, toda la cadena que hasta ahora había que ejecutar como
cuatro procesos separados -- 'Extracción de traza', 'Calibrar por
estrella de referencia', 'Identificar líneas automáticamente' e
'Informe de control de calidad' -- reutilizando literalmente los mismos
motores, nunca duplicando la física de ninguno.

## Diseño

- `astrophysics_suite/spectroscopy/autoprocess.py` (nuevo módulo,
  numpy puro, comprobable sin Qt): `run_autoprocess_spectrum()` corre
  cinco etapas en orden --
  1. **Traza espacial** (`trace.trace_spectrum`) -- obligatoria, un
     fallo se propaga como `ValueError` (no hay nada real que informar
     sin ella, misma disciplina que ya tenía `spectroscopy.trace`).
  2. **Extracción** (`trace.extract_sum`/`extract_mean`/`extract_optimal`,
     el `extractor` ya resuelto se pasa como parámetro -- este módulo de
     ciencia pura no conoce el diccionario de nombres en español de la
     GUI) -- también obligatoria.
  3. **Calibración en longitud de onda por estrella de referencia**
     (§13, `reference_star_calibration.calibrate_from_reference_star`)
     -- OPCIONAL: un `ValueError` real (sin líneas que emparejar, p. ej.)
     se captura y se registra como paso `error` con el motivo real, sin
     interrumpir el autoproceso -- traza y extracción ya completadas
     siguen disponibles.
  4. **Identificación de líneas** (§10/§21,
     `object_line_identification.identify_object_lines_in_spectrum`) --
     OPCIONAL, y se omite automáticamente (con el motivo) si el paso 3
     no produjo una calibración real: sin ella no hay eje de longitud de
     onda real sobre el que identificar nada.
  5. **Informe de calidad** (§31/§42, `qc_report.QCReport`) -- siempre
     se calcula, con `N/D` honesto en las filas que dependan de una
     calibración que no se completó.
- Cada etapa queda en un `AutoprocessStep(name, status, detail)` --
  `status` es «ok»/«omitido»/«error», nunca «ok» si la etapa no se
  completó de verdad. `AutoprocessResult.overall_ok` es `False` si
  cualquier etapa quedó en «error» (incluida una calidad global `ERROR`,
  p. ej. S/N muy baja) -- el botón nunca informa éxito solo porque no
  hubo una excepción.
- Explícitamente FUERA de alcance (documentado en el docstring del
  módulo): bias/dark/flat (correcciones de TODO el fotograma CCD, no
  específicas de espectroscopía -- se aplican antes, desde el menú
  "Reducción", sobre cualquier imagen) y calibración de flujo (sensfunc,
  necesita un espectro de estrella ESTÁNDAR aparte, no derivable de la
  imagen activa). La calibración por lámpara de arco tampoco se
  automatiza (exige emparejar a mano cada línea) -- el autoproceso usa
  en su lugar la calibración automática por estrella de referencia y
  hereda su aviso: PROVISIONAL, nunca al nivel de una lámpara real.
- `qt_app/processes/registry.py`: `_run_autoprocess_spectrum` resuelve
  parámetros de la GUI (método de extracción, catálogos, tolerancias,
  suavizado de cielo, perfil de instrumento, `OBJECT` real de la
  cabecera como `reference_object`) y llama al motor. El resultado se
  expone con las MISMAS claves de artefacto que ya usan los procesos
  individuales (`spectrum`, `trace_overlay`, `wavelength_calibration_
  record`, `wavelength_calibration_spectrum`) -- `main_window.
  _on_process_finished` ya sabía enhebrarlas de vuelta sobre la vista
  (abre la ventana de espectro, dibuja el overlay, y si la calibración
  tuvo éxito deja `view.fitted_wavelength_solution` lista para
  "Guardar espectro calibrado (FITS)..." y el resto del taller) sin
  tocar `main_window.py` en absoluto.
- Pequeño refactor sin cambio de comportamiento: se extrajo
  `_qc_report_table(report)` de `_run_qc_report` para que
  `_run_autoprocess_spectrum` reutilice la misma construcción de tabla
  en vez de duplicarla.
- Nuevo proceso `spectroscopy.autoprocess` ("Autoprocesar espectro
  (§34)") en el explorador, categoría Espectroscopía, `requires_picking=1`
  (mismo clic de centro de traza que ya usan 'Extracción de traza' e
  'Informe de calidad').

## Validación

- `ruff check`: limpio en los tres archivos tocados/nuevos.
- `tests/unit/spectroscopy/test_autoprocess.py` (nuevo, 4 tests): cadena
  completa con recuperación real de una calibración conocida (síntesis
  2D: perfil espacial gaussiano x depresiones reales de Balmer en las
  columnas correctas); calibración/identificación omitidas cuando se
  desactivan; fallo real de calibración capturado sin perder la
  extracción (`overall_ok is False`); fallo real de traza (centro fuera
  de la imagen) propagado como excepción, nunca ocultado.
- `tests/unit/qt_app/test_registry.py` (+4 tests): exige un clic;
  cadena completa enhebra `wavelength_calibration_record`/`_spectrum`
  reales (mismas claves que 'Calibrar por estrella de referencia'),
  tabla de 6 filas, 5 líneas de registro todas «ok», marcadores de
  líneas identificadas en la gráfica; calibración desactivada no
  enhebra ningún artefacto de calibración y deja el eje en píxel;
  fallo real de calibración se reporta como «error» sin perder el
  artefacto `spectrum`.
- `tests/gui_smoke/test_qt_app_autoprocess_smoke.py` (nuevo, 1 test):
  clic real de extremo a extremo vía `main_window._run_process` sobre
  una síntesis 2D con Balmer real -- confirma que se abre exactamente
  una ventana de espectro nueva, la tabla de resultado tiene 6 filas, y
  `view.fitted_wavelength_solution`/`view.wavelength_calibration_record`
  quedan enhebrados sobre la VISTA DE ORIGEN (no la ventana nueva) listos
  para el resto del taller, con el overlay de traza real dibujado.
- Suite unitaria completa: **1044 passed** (antes: 1036).
- Suite de humo GUI completa: **190 passed** (antes: 189).
- Validación real sobre `Vega_1sec_1x1__frame6.fit` (vía
  `qt_app.processes.registry`, mismo clic y=602.0 ya validado en slices
  anteriores): traza real (RMS=0.08 px), extracción real (S/N
  mediana=302.6), informe de calidad completo (`OK`) -- la calibración
  por estrella de referencia falla LIMPIAMENTE con la misma dispersión
  de referencia aproximada (1.4 Å/px) ya usada en el informe 76 (slice
  21), tanto con tolerancia ajustada (5 Å) como con la tolerancia por
  defecto del proceso (15 Å): **mismo resultado honesto ya documentado
  en el informe 76 para este archivo concreto** (sin lámpara real
  adjuntada, 0 de 15 detecciones reales cae dentro de tolerancia) -- lo
  que valida aquí es que el autoproceso reproduce ese mismo límite real
  de los datos SIN perder la traza/extracción/informe de calidad ya
  completados, exactamente el comportamiento de degradación honesta que
  motiva todo el diseño de este slice.

## Qué queda fuera

§35 (modo manual/reinicio explícito), §36 (historial de procesamiento en
JSON), §37 (nomenclatura estándar de productos) y §39 (trazabilidad de
cadena completa) dependían de que existiera §34 -- ahora existe, pero
implementarlos es trabajo propio de un slice dedicado (persistencia a
disco, no solo orquestación en memoria) y queda para el siguiente.
