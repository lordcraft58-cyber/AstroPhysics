# 88 — Cierre del hueco de `input_hashes` en Provenance (Reducción/Astrometría/Detección)

Continuación de los cierres de motor 1-5. Los informes 52
(Reducción), 53 (Astrometría) y 54 (Detección) anotaban, cada uno por
separado, el mismo hueco real: `Provenance.input_hashes` existía desde
la Fase 4 -- el contrato lo pedía y el sha256 real de cualquier entrada
siempre estuvo disponible vía `io.fits_reader.sha256_file` -- pero
ningún llamador lo rellenaba nunca. Un producto derivado (LIGHT
reducido, copia con WCS, detección) no declaraba de qué entrada exacta
salía.

## Por qué no se cerró antes

El informe 52 lo explicaba: "rellenarlo exige que la biblioteca de
maestros guarde el hash de sus propias entradas, que hoy no hace" --
`MasterFrame`/`build_master_bias`/`build_master_dark`/`build_master_flat`
operan sobre `list[np.ndarray]` puros, sin ninguna referencia a archivo.
Y `reduce_light_frames` declara explícitamente que "la capa de ciencia
nunca toca el sistema de archivos" -- no iba a empezar a leer/hashear
archivos por su cuenta.

## Diseño: el hash se calcula en la GUI, nunca en la capa de ciencia

En vez de romper esa frontera, cada motor de ciencia gana un parámetro
opcional de solo texto (`light_hashes`, `master_bias_hash`, ...,
`input_hashes` en `build_wcs_provenance`) -- strings que el LLAMADOR ya
tiene o puede calcular, nunca releídos ni recalculados dentro del
motor:

- **Detection**: `io.fits_loader.load_image`/`build_observation` YA
  calculan `ImageRef.sha256` al cargar cualquier imagen -- `detect_
  point_sources` solo tenía que leer ese campo, que ya tenía delante.
  Cero coste nuevo de E/S.
- **Reducción**: `reduce_light_frames` gana `light_hashes` (paralelo a
  `light_paths`, misma validación de longitud) y `master_bias_hash`/
  `master_dark_hash`/`master_flat_hash`. `ReduceSessionDialog` reutiliza
  `loaded[i].image_ref.sha256` de las LIGHTS ya cargadas (gratis), y
  calcula el hash de un maestro SOLO si `NamedMasterFrame.path` es real
  (un maestro guardado en disco) -- uno recién combinado en memoria y
  nunca guardado no tiene archivo que hashear, y no se inventa uno.
- **Astrometría**: `build_wcs_provenance` gana `input_hashes`; `_offer_
  to_save_wcs_fits_copy` (main_window.py) calcula `sha256_file(view.
  source_path)` -- pero con manejo honesto de `OSError`: `source_path`
  puede apuntar a un archivo movido/borrado desde que se cargó, y un
  fallo al releerlo aquí NUNCA debe impedir guardar la copia con WCS en
  sí (encontrado por una prueba de humo GUI existente que usaba un
  `source_path` nominal sin archivo real detrás -- rompió las 6 pruebas
  del archivo antes de añadir el `try/except`).

## Cómo llega el hash al archivo de salida

Reducción y Astrometría ya escribían `HISTORY` en el FITS de salida --
`input_hashes` se añade ahí, reutilizando `io.fits_writer.wrap_history_
lines` (la misma utilidad ya usada por `astrometry.wcs_header_cards`,
antes NO usada por `reduction.reduction_header_cards`, que construía su
`HISTORY` a mano). Un sha256 tiene 64 caracteres, más que el ancho real
de una tarjeta `HISTORY` (~72 caracteres) menos cualquier etiqueta --
`wrap_history_lines` parte por palabras sin cortar nunca un hash a
mitad (`break_long_words=False`), así que cada hash sale en dos líneas
reales: `# entrada: <etiqueta>` seguida del hash solo. Refactorizar
`reduction_header_cards` para usar la misma utilidad que Astrometría
cierra además una inconsistencia real entre los dos módulos.

Detection no escribe sus detecciones a un FITS propio (viven en memoria
como `Detection.provenance`, luego se serializan a JSON en la sesión
guardada) -- ahí no hay límite de ancho de tarjeta, así que se guarda la
ruta completa de origen, no solo el nombre.

## Validación

- `ruff check astrophysics_suite qt_app tests`: limpio.
- `tests/unit/reduction/test_session_pipeline.py` (+3 tests): hashes
  reales de LIGHT y maestros llegan a `provenance.input_hashes`;
  longitud de `light_hashes` validada; ningún hash inventado para un
  maestro nunca guardado.
- `tests/unit/reduction/test_reduction_provenance.py` (+1 test): los
  hashes reales sobreviven un ciclo completo de guardado/relectura FITS
  como líneas `HISTORY`.
- `tests/unit/detection/test_point_sources.py` (+1 test): el sha256 real
  del FITS de origen (`ImageRef.sha256`, ya calculado al cargar) llega
  tal cual a `Detection.provenance.input_hashes`.
- `tests/unit/astrometry/test_astrometry_provenance.py` (+1 test): mismo
  ciclo de guardado/relectura FITS para `wcs_header_cards`.
- `tests/gui_smoke/test_qt_app_reduce_session_smoke.py` (+1 test): flujo
  real de extremo a extremo por el diálogo -- LIGHT real cargado, maestro
  guardado en disco vs. maestro nunca guardado, ambos casos correctos en
  el FITS de salida.
- `tests/gui_smoke/test_qt_app_wcs_fits_copy_smoke.py` (+2 tests): hash
  real cuando el archivo de origen existe de verdad; degradación honesta
  (sin hash, sin fallo) cuando no existe -- la prueba que expuso la
  necesidad del `try/except` en `main_window.py`.
- Suite unitaria completa: **1690 passed** (antes: 1685).
- Suite de humo GUI completa: **208 passed** (antes: 205).
- Validación real sobre `Light_M_31_300.0s_Bin1_...0001.fit`: el sha256
  real del archivo (`a0804d6f...`) llega intacto tanto a `Detection.
  provenance.input_hashes` como a `LightFrameReduction.provenance.
  input_hashes` tras pasar por `detect_point_sources`/`reduce_light_
  frames` respectivamente.

## Qué queda

- Ninguno de los tres motores tenía este hueco documentado en ningún
  otro sitio salvo los informes 52/53/54, ya citados aquí -- cerrados
  los tres.
- El hash de un maestro construido en la MISMA sesión pero nunca
  guardado a disco sigue, deliberadamente, sin aparecer -- no hay
  ningún archivo real que hashear hasta que el usuario lo guarda. Si se
  quisiera trazabilidad también para ese caso, haría falta que
  `MasterFrame` guardara los hashes de SUS propias entradas (los
  sub-fotogramas bias/dark/flat individuales) -- cambio de contrato más
  profundo, fuera de alcance de este cierre puntual.
