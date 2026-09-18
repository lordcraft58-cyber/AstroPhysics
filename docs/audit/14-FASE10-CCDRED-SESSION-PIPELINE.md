# AstroPhysics Suite — Fase 10.1: pipeline de reducción CCD por sesión

Cierra el hueco principal que señala `13-IRAF-CAPABILITY-MAP.md` en el bloque
`ccdred`: hasta esta fase, la GUI solo podía calibrar **una imagen activa a la vez**
("Aplicar calibración..."). El encargo pide explícitamente un flujo capaz de
trabajar con las LUCES reales de una sesión completa, no solo con productos ya
combinados: RAW/FITS → OVERSCAN → TRIM → MASTER BIAS/DARK/FLAT → CALIBRACIÓN DE
LIGHTS → COMBINACIÓN → RECHAZO DE OUTLIERS → PRODUCTO CALIBRADO. Esta fase entrega
exactamente ese flujo, sin tocar ningún otro bloque (orden de prioridad acordado:
`ccdred` antes que análisis de imagen/fotometría/astrometría).

## 1. Motor científico nuevo (`astrophysics_suite/`, sin ningún cambio de GUI)

- `astrophysics_suite/reduction/session_pipeline.py` -- `reduce_light_frames()`:
  orquesta, para una **lista real de LIGHTS** (no una imagen), la misma cadena
  física fija que ya usaba `calibrate_frame` para una sola imagen (overscan/recorte
  opcional -> bias -> dark escalado por exposición -> flat -> píxeles defectuosos
  interpolados -> franjas opcional), y añade opcionalmente la combinación final con
  el mismo rechazo robusto de outliers (`combine.combine_images`, sigma-clip por
  MAD) que ya usan los fotogramas maestros -- aplicado ahora a ciencia real, no solo
  a calibración. No reimplementa ninguna matemática: cada paso delega en el motor
  ya existente y probado (`overscan.py`, `calibration.py`, `combine.py`,
  `fringe.py`), esta función solo encadena.
- `astrophysics_suite/io/fits_writer.py` -- `save_fits_image()`: contrapartida
  simétrica de `fits_loader.load_image`, para que los productos calibrados de una
  sesión puedan escribirse a disco sin que la capa de ciencia toque el sistema de
  archivos (esa disciplina se mantiene: `session_pipeline.py` nunca escribe nada,
  solo devuelve arrays en memoria).

Con esto, dos capacidades que el Mapa de capacidades marcaba como `PENDIENTE` por
falta de camino de uso quedan cerradas en el mismo movimiento: la máscara de
píxeles defectuosos (`bad_pixel_mask.py`, ya existía pero ningún diálogo la
construía) y la corrección de franjas (`fringe.py`, ni proceso ni diálogo la
exponía) -- ambas eran motores reales sin ninguna forma de invocarlos desde la
aplicación; ahora son parámetros opcionales del mismo pipeline de sesión.

Un fotograma maestro ya construido sigue pudiendo usarse como producto derivado
(vía `master_bias`/`master_dark`/`master_flat`), pero esto nunca sustituye la
capacidad de reducir las LIGHTS originales -- instrucción explícita del encargo,
porque los mismos píxeles crudos hacen falta después para el análisis temporal y
otros motores de descubrimiento.

## 2. GUI (`qt_app/reduction/reduce_session_dialog.py`)

Nuevo diálogo "Reducir sesión de LIGHTS..." (menú Reducción, junto a "Construir
fotograma maestro..." y "Aplicar calibración..."):

- Selección de **N archivos LIGHT** a la vez (mismo patrón de lista + "Añadir..."
  que ya usaba "Construir fotograma maestro").
- Fotogramas maestros elegidos por nombre de la `MasterFrameLibrary` de la sesión
  (reutiliza lo que ya exista, no obliga a reconstruirlos).
- Corrección de píxeles defectuosos: casilla que, si hay un flat maestro
  seleccionado, construye la máscara automáticamente desde él
  (`build_bad_pixel_mask`) -- el usuario no tiene que fabricarla a mano.
- Patrón de franjas maestro opcional (un único archivo).
- Overscan y recorte opcionales, con las regiones como filas/columnas de inicio y
  fin.
- Ganancia y ruido de lectura (mismos campos que ya tenía "Aplicar calibración").
- Combinación final opcional (activada por defecto): método mediana/media y umbral
  de rechazo de outliers en sigmas.
- Carpeta de salida: cada LIGHT calibrado se escribe como
  `<nombre>_calibrada.fits`, y el combinado (si se pidió) como `combinada.fits` --
  con la cabecera original de cada archivo preservada donde tiene sentido (el
  combinado descarta `EXPTIME` explícitamente: atribuírselo sin más sería una
  mentira, un producto apilado no tiene un único tiempo de exposición).

**Mejora real frente al diálogo de una sola imagen**: el tiempo de exposición de
cada LIGHT se lee automáticamente de su propia cabecera FITS (`EXPTIME`) en vez de
pedírselo al usuario a mano por cada imagen -- si un archivo no lo tiene y hace
falta para escalar un dark maestro, el error nombra exactamente qué archivo falta,
en vez de fallar de forma genérica.

Ejecuta en un hilo de fondo real (`qt_app.workers.CallableWorker`, el mismo
mecanismo que ya usaban los otros diálogos de reducción) -- la GUI no se congela
durante la reducción de una sesión con muchos archivos. No abre una ventana MDI por
cada LIGHT calibrado (sería impracticable para una sesión real de decenas de
exposiciones); solo abre el combinado, si se produjo uno, porque es el artefacto
que de verdad se quiere inspeccionar visualmente -- cada calibrado individual queda
en disco, disponible vía "Abrir FITS..." si hace falta.

## 3. Verificación

- **Motor**: `tests/unit/reduction/test_session_pipeline.py` (9 tests) --
  cadena completa por LIGHT, rutas/exposiciones de longitud incorrecta rechazadas,
  overscan+recorte aplicado por fotograma, corrección de franjas recuperando el
  factor de escala exacto, combinación con rechazo real de un rayo cósmico
  inyectado en un único fotograma (verificado que `n_combined` baja exactamente en
  ese píxel), y un caso de extremo a extremo (RAW con overscan -> recorte ->
  bias/dark/flat -> combinación) verificado contra un cálculo de referencia hecho a
  mano fuera del pipeline, no contra el propio código.
- **Escritura de FITS**: `tests/unit/io/test_fits_writer.py` (5 tests) -- roundtrip
  de píxeles, copia de claves de cabecera serializables, claves no serializables
  ignoradas sin fallar, creación de carpetas de salida que no existían,
  `overwrite=False` respetado.
- **GUI de extremo a extremo real**:
  `tests/gui_smoke/test_qt_app_reduce_session_smoke.py` (2 tests) -- escribe bias/
  dark/flat/LIGHTS sintéticos reales a disco (un píxel del flat deliberadamente
  defectuoso presente en los tres planos, un rayo cósmico inyectado en una sola
  LIGHT), construye los maestros con el motor real, ejecuta el diálogo con el hilo
  de fondo real, **relee los FITS calibrados escritos por el propio diálogo** y
  confirma: el píxel defectuoso queda interpolado a un valor correcto en cada
  fotograma individual, el rayo cósmico sigue presente en su fotograma individual
  (cada calibrado conserva sus propios píxeles) pero desaparece del combinado
  (rechazado por el sigma-clip), y el combinado se abre como ventana MDI nueva. Un
  segundo test confirma que un LIGHT sin `EXPTIME` en la cabecera produce un
  mensaje de error que nombra el archivo, en vez de un fallo silencioso o un
  cuelgue de la GUI (`QMessageBox.critical` interceptado con `monkeypatch`, mismo
  patrón que ya usaba `test_qt_app_smoke.py` para no bloquear la prueba bajo Xvfb).

Suite completa verde en ambos entornos tras este cambio: 308 tests en el entorno
con PySide6 (`aps-gui`), 266 en el entorno sin GUI (`aps-test`), más `ruff` limpio
en los archivos nuevos/tocados.

## 4. Qué queda del bloque `ccdred` (documentado, no oculto)

Ver el detalle completo en `13-IRAF-CAPABILITY-MAP.md` §1. Quedan explícitamente
`PENDIENTE`, no abordados en esta fase porque no son necesarios para que la sesión
de LIGHTS funcione de verdad: corrección de iluminación, corrección de cielo,
clasificación automática de fotogramas por cabecera (`IMAGETYP`), y perfiles de
configuración por instrumento (ganancia/ruido de lectura/geometría de overscan
guardados por cámara en vez de reintroducidos cada vez). Se documentan aquí para
que una fase posterior decida si son necesarios antes de avanzar al siguiente
bloque (análisis de imagen), siguiendo el orden de prioridad acordado.
