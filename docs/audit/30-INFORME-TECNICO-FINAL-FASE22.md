# 30 — Informe técnico final (Fase 22: corrección profunda tras uso real en Windows)

Responde punto por punto al encargo detallado que reportó Discovery
fallando siempre en Windows con datos reales, y pidió: corregirlo de
raíz, añadir plate solving automático real, integrarlo en Discovery,
guardar fotogramas maestros en una ruta elegida, un tutorial guiado de
primer arranque, y este mismo informe. **Ningún componente se marca
aquí como "completo" o "funcionando" sin haber sido ejecutado y
validado realmente** (ver §11 para los límites honestos de esa
validación -- en particular, todo lo de abajo se probó en este
contenedor Linux sandboxed, nunca en la máquina Windows real del
usuario ni con sus archivos FITS reales).

## 1. Error exacto de Discovery encontrado

`Descubrimiento falló: 'D:\Plan\Light\M 31\Light_M 31_300.0s_Bin1_20260915-063714_340deg_0095.fit'`

Reportado como el mismo patrón en TODOS los análisis, cualquiera fuera
la imagen. El formato del mensaje -- una ruta entre comillas simples,
sin ningún texto adicional -- es la firma inconfundible de
`str(KeyError(x))` en Python, lo que dirigió la investigación
directamente a código de búsqueda en diccionario, no a WCS/Gaia (que es
justo lo que el mensaje parecía sugerir, y no tenía nada que ver).

## 2. Causa raíz

`astrophysics_suite/io/fits_loader.py`, función `build_observation`:
indexaba el diccionario `loaded_by_resolved_path` (que `discovery/
pipeline.py` usa para encontrar cada imagen ya cargada) por la ruta
CRUDA que pasó el llamador, no por la ruta que `ImageRef.path` acabó
teniendo de verdad (`Path(path).resolve()`, calculada dentro de
`load_image`). Esas dos formas de texto pueden diferir aunque señalen
al mismo archivo: una ruta relativa se vuelve absoluta, y en Windows,
`QFileDialog` devuelve rutas con `/` mientras que `pathlib.Path.resolve()`
normaliza a `\` -- exactamente el caso real reportado. `run_generic_
discovery` busca cada imagen por `image_ref.path`; si el diccionario se
indexa por la ruta cruda, esa búsqueda falla con un `KeyError` real
siempre que las dos formas no coincidan carácter a carácter -- en la
práctica, siempre en Windows con `QFileDialog`.

Confirmado como causa real, no solo sospechada: reproducido de forma
determinista con una ruta relativa (`git stash` de la corrección →
falla con el mismo mensaje → `git stash pop` → pasa).

## 3. Archivos modificados (corrección del KeyError)

- `astrophysics_suite/io/fits_loader.py` -- `build_observation` ahora
  indexa por `loaded_image.image_ref.path`.
- `tests/unit/io/test_fits_loader.py`,
  `tests/unit/services/test_discovery_service.py` -- regresión con ruta
  relativa reproduciendo el bug exacto.

Documentado en detalle en `docs/audit/25-FIX-DISCOVERY-KEYERROR-RUTA.md`
(incluye el hallazgo honesto de que, de los 7 valores de
`IdentificationState`, la ruta moderna de Discovery solo alcanza 3:
KNOWN, UNMATCHED, DISCOVERY_REVIEW -- KNOWN_VARIANT/ANOMALOUS son
exclusivos del pipeline heredado antiguo, y TRANSIENT_CANDIDATE/
MOVING_SOURCE_CANDIDATE no los produce ningún código real todavía).

Un segundo bug real, reportado a mitad de la sesión ("tampoco deja abrir
imágenes de 3 dimensiones"), se corrigió en el mismo bloque de trabajo:
`AmbiguousCubeError` (diseño correcto y deliberado -- nunca elige un
plano en silencio) no tenía ningún camino de GUI para que el usuario
indicara el plano. Corregido con `probe_fits_shape` +
`CubePlaneDialog` + `open_fits` capturando la excepción y reintentando
con el plano elegido (`docs/audit/26-FIX-ABRIR-FITS-3D.md`).

## 4. Cambios realizados (resumen completo de la ronda)

1. **Discovery**: corrección del KeyError (§2-3) + apertura de FITS 3D/4D.
2. **Plate solving automático** (`astrophysics_suite/astrometry/
   plate_solve.py`, nuevo) -- ver §5.
3. **Integración en Discovery** (`astrophysics_suite/discovery/
   pipeline.py`) -- WCS automático antes de detectar/identificar.
4. **Guardado de fotogramas maestros en ruta elegida**
   (`astrophysics_suite/reduction/master_frames.py`,
   `qt_app/reduction/build_master_frame_dialog.py`,
   `services/app_preferences.py`, nuevo) -- ver §7.
5. **Tutorial guiado de primer arranque** (`qt_app/tutorial/`, nuevo) --
   ver §8.

Detalle técnico completo de cada bloque en sus propios documentos:
`docs/audit/27-PLATE-SOLVING-AUTOMATICO.md`,
`docs/audit/28-MASTER-FRAME-RUTA-DE-SALIDA.md`,
`docs/audit/29-TUTORIAL-GUIADO.md`.

## 5. Cómo se implementó el plate solving automático

`astrophysics_suite/astrometry/plate_solve.py`, `solve_plate(data,
header, ...)`. Alcance real, no "blind solving" completo al estilo
astrometry.net (ver razones en el propio módulo): requiere un puntero
(RA/Dec) y una escala aproximados -- del header FITS
(`OBJCTRA`/`OBJCTDEC` u `RA`/`DEC`, `PIXSCALE`/`SECPIX` o
`FOCALLEN`+`XPIXSZ`) o dados por el usuario -- y resuelve la orientación
exacta (rotación + posible espejo) con estrellas reales:

1. Detecta estrellas reales (`detect_point_sources_in_array`, mismo
   motor que el resto de la app).
2. Consulta Gaia real alrededor del puntero aproximado.
3. Busca la orientación por rejilla de rotación/paridad, emparejando
   por **votación de traslación** (ver el bug real corregido más abajo).
4. Empareja 1-a-1 por vecino mutuo y ajusta un WCS real por mínimos
   cuadrados (`fit_wcs`, ya existente), con rechazo iterativo sigma-clip
   de parejas mal emparejadas.
5. Valida: nº mínimo de estrellas emparejadas, RMS máximo. Si no se
   cumple, o si falta puntero/escala, `success=False` con el motivo
   exacto -- nunca inventa una solución.

Proveedor reportado: `"local (rejilla de rotación + emparejamiento Gaia,
sin binario/servicio externo)"` -- decisión deliberada de no envolver
astrometry.net/ASTAP (política del proyecto contra envolver herramientas
de terceros de alto nivel, y este sandbox no tiene salida de red para
descargar binarios/índices de varios GB).

**Bug real encontrado y corregido durante el desarrollo** (no solo un
ajuste de umbral): la búsqueda de orientación alineaba el catálogo
proyectado con las estrellas detectadas por CENTROIDE -- asumiendo que
el centroide detectado aproxima el del catálogo completo. Esa asunción
se rompe en cuanto la detección es incompleta (p. ej. estrellas dobles
próximas que el detector fusiona en una sola fuente, algo normal en
datos reales). Reproducido con un caso concreto: 35 estrellas
sintéticas, puntero/escala EXACTOS (el caso más favorable posible), 7
sin detectar por fusión de pares próximos -- la orientación correcta
puntuaba 5 correspondencias en la rejilla, una orientación incorrecta
(espejada) puntuaba 16, y el ajuste final daba RMS=4.8" en vez de fallar
por la razón correcta. Corregido sustituyendo la alineación por
centroide por una **votación de traslación tipo Hough** (para cada
hipótesis de rotación/paridad, la traslación más votada entre todas las
parejas posibles detectado-catálogo), robusta a una submuestra de
detecciones no representativa. Verificado: RMS del caso 4.76" → 0.008",
y 25 combinaciones adicionales de semilla/rotación/espejo, todas
convergiendo con RMS < 0.01".

GUI: **Astrometría → Resolver placa automáticamente...** (nuevo, primera
opción del menú), con **Ajustar WCS manualmente...** conservado como
alternativa explícita (relabeleado como respaldo).

## 6. Cómo se propaga y guarda el WCS

- Manual o automático, el resultado es un `WCSSolution` propio
  (`astrophysics_suite/astrometry/wcs_fit.py`).
- `wcs_solution_to_astropy(solution)` (nuevo, inversa real de
  `wcs_solution_from_astropy`, ya existente) lo convierte a un
  `astropy.wcs.WCS` real.
- Tras resolver automáticamente, `MainWindow` asigna el WCS a la
  ventana (`view.fitted_wcs_solution`) y ofrece guardar una copia del
  FITS con el WCS escrito en la cabecera real (`save_fits_image`, ya
  existente desde la Fase 10.1) -- verificado reabriendo el archivo con
  astropy y comprobando que las coordenadas resueltas coinciden.
- **Integrado en Discovery**: `run_generic_discovery` (`astrophysics_
  suite/discovery/pipeline.py`), antes de detectar fuentes en cada
  imagen, comprueba su WCS (`_ensure_wcs`): si ya lo tiene, no hace
  nada; si falta y `auto_plate_solve=True` (por defecto, casilla en
  "Nueva observación"), intenta `solve_plate` y, si resuelve, asigna el
  WCS real a la imagen cargada (`legacy_image.wcs`) ANTES de que el
  resto del pipeline la toque -- el resto del código (detección,
  identificación) lo usa exactamente igual que si viniera en el FITS.
  Si no puede resolver, se registra el motivo exacto y la imagen sigue
  el análisis sin coordenadas celestes -- nunca una excepción, nunca un
  WCS inventado. Cuatro estados reales por imagen
  (`ImageWCSStatus.state` en `DiscoveryRunSummary.wcs_status`):
  `WCS_PRESENTE`, `WCS_RESUELTO_Y_VALIDADO_AUTOMATICAMENTE`,
  `PLATE_SOLVING_FALLIDO`, `PLATE_SOLVING_NO_EJECUTADO` -- registrados
  en la consola integrada y resumidos en la barra de estado al terminar
  el análisis.

## 7. Cómo se elige la ruta de salida de los maestros

`qt_app/reduction/build_master_frame_dialog.py`: campo "Carpeta/archivo
de salida" + botón "Examinar..." (`QFileDialog.getSaveFileName` real).
Nombre propuesto = última carpeta usada (`services/app_preferences.py`,
JSON bajo `~/.astrophysics_suite/`, mismo patrón que
`instrument_profiles.py`) + nombre del maestro; deja de actualizarse en
cuanto el usuario edita la ruta a mano. `.fits` se añade automáticamente
si falta. Si el archivo ya existe, se pide confirmación antes de
sobrescribir.

El resultado no vive solo en memoria: `astrophysics_suite/reduction/
master_frames.py` gana `save_master_frame`/`load_master_frame` -- un
FITS real de 3 HDUs (datos + extensiones `UNCERT`/`NCOMBINE`), porque
`calibration.py` propaga de verdad la incertidumbre del maestro al
calibrar; guardar solo los datos y rellenar la incertidumbre con ceros
al releer habría falseado esa propagación. `load_master_frame` rechaza
con un error explícito cualquier FITS que no tenga esa forma exacta.
Solo tras escribir con éxito se registra el maestro en
`MasterFrameLibrary`, con su ruta real. "Reducción → Cargar fotograma
maestro..." (nuevo) reabre un FITS ya guardado -- así es como un maestro
de una sesión anterior se reutiliza, sin introducir una base de datos
propia (deliberado, como pide el encargo).

## 8. Cómo funciona el tutorial de primer arranque

`qt_app/tutorial/` (nuevo): 12 pasos reales (Bienvenida, Explorador de
procesos, Abrir FITS, Visualización, Reducción, Astrometría, Fotometría,
Espectroscopía, Discovery, Candidatos, Exportación, Final), cada uno
resaltando un control REAL de `MainWindow` (menú, dock o área central) a
través de una función que resuelve su geometría contra la ventana actual
en cada momento -- nunca un control inventado; si el control no está
disponible, el paso no resalta nada en vez de señalar un lugar
equivocado. Cada paso contextual cubre QUÉ HACE/CUÁNDO USARLO/QUÉ
NECESITA/QUÉ PRODUCE.

Aparece la primera vez (preferencia `tutorial_show_on_startup`, sin
fijar todavía) y deja de aparecer solo en cuanto se completa o se salta;
"Ayuda → Mostrar tutorial al iniciar" lo reactiva, "Ayuda → Tutorial
guiado" siempre lo reabre manualmente. Se dispara desde
`qt_app/__main__.py` (el arranque real), nunca desde el constructor de
`MainWindow`, para que las ~80 pruebas de humo GUI ya existentes (que
construyen `MainWindow()` directamente) nunca se vean afectadas por una
ventana emergente.

Dos bugs reales de renderizado encontrados y corregidos durante el
desarrollo (verificados con capturas de pantalla reales antes/después,
no solo por inspección de código): elevar la pestaña tabificada de
CANDIDATOS reordenaba el apilamiento de `QMainWindow` y dejaba la capa
del tutorial por debajo (el panel de texto desaparecía); y el "hueco"
que resalta el control, con `CompositionMode_Clear`, dejaba de revelar
el contenido real en cuanto la capa volvía a estar por encima. Ambos
corregidos (detalle en `docs/audit/29-TUTORIAL-GUIADO.md` §4).

## 9. Tests ejecutados

Dos entornos, como en toda la sesión: `aps-test` (sin PySide6, unit +
integration + regression) y `aps-gui` (con PySide6, suite completa
incluidos los tests de humo GUI, bajo Xvfb `:99`).

- `aps-test`: `pytest tests/unit tests/regression tests/integration`
- `aps-gui`: `pytest tests/` (incluye también unit/integration/
  regression, más `tests/gui_smoke/`)

Archivos de test nuevos o ampliados esta ronda: `tests/unit/io/
test_fits_loader.py`, `tests/unit/services/test_discovery_service.py`,
`tests/gui_smoke/test_qt_app_smoke.py` (apertura de FITS 3D),
`tests/unit/astrometry/test_plate_solve.py` (nuevo, 13 tests),
`tests/unit/astrometry/test_wcs_fit.py` (+2),
`tests/gui_smoke/test_qt_app_plate_solve_smoke.py` (nuevo, 3 tests),
`tests/integration/test_generic_discovery_pipeline.py` (+4, WCS
automático en Discovery), `tests/unit/reduction/test_master_frames.py`
(+6), `tests/unit/services/test_app_preferences.py` (nuevo, 4 tests),
`tests/gui_smoke/test_qt_app_reduction_smoke.py` (+5, y 2 existentes
ampliados), `tests/gui_smoke/test_qt_app_tutorial_smoke.py` (nuevo, 6
tests).

## 10. Resultados de los tests

Última ejecución completa de la ronda, ambos entornos, sin fallos:

- `aps-test`: **397 passed, 3 skipped** (68 s)
- `aps-gui`: **491 passed, 2 skipped, 1 xfailed** (37 s)

Los `skipped`/`xfailed` son preexistentes a esta ronda (dependencias
opcionales ausentes / un `xfail` documentado de una fase anterior), no
introducidos por este trabajo. Ningún test se marcó como skip o xfail
para evitar un fallo real de esta ronda.

**Correspondencia explícita con la lista obligatoria A-O del encargo:**

| # | Prueba | Dónde |
|---|--------|-------|
| A | Regresión del error exacto de Discovery | `test_discovery_job_completes_when_input_path_differs_from_its_resolved_form` |
| B | Discovery sin WCS | `test_run_generic_discovery_end_to_end`, `test_run_generic_discovery_records_plate_solve_failure_without_crashing` |
| C | Discovery con WCS válido | `test_discovery_job_reaches_known_and_unmatched_with_real_wcs_and_mocked_gaia`, `test_run_generic_discovery_reports_wcs_present_and_never_calls_solve_plate` |
| D | Plate solving con datos controlados | `test_solve_plate_recovers_true_wcs_with_approximate_pointing_and_scale` y 12 más en `test_plate_solve.py` |
| E | Fallo del solver | `test_solve_plate_fails_honestly_*` (5 tests) + `test_run_generic_discovery_records_plate_solve_failure_without_crashing` |
| F | WCS escrito en el FITS | `test_saving_wcs_fits_copy_writes_a_real_solvable_header`, `test_wcs_solution_to_astropy_writes_a_real_fits_header` |
| G | FITS reabierto conserva el WCS | mismos tests que F (reabren con astropy y verifican coordenadas) |
| H | Master Bias guardado en ruta elegida | `test_build_master_bias_end_to_end` (ampliado) |
| I | Master Dark con exposición | `test_build_master_dark_records_exposure_and_saves_real_fits` |
| J | Master Flat | `test_save_and_load_master_flat_preserves_normalization_and_filter`, `test_build_master_flat_normalizes_and_saves_real_fits` |
| K | Confirmación de sobrescritura | `test_build_master_frame_requires_confirmation_before_overwriting` |
| L | Tutorial en el primer arranque | `test_tutorial_shows_on_first_launch` |
| M | Tutorial no reaparece tras completarse | `test_tutorial_does_not_reappear_once_completed` |
| N | Reapertura manual del tutorial | `test_tutorial_can_be_reopened_manually_after_completion` |
| O | Prueba de humo GUI completa | suite completa `aps-gui`: 491 passed |

## 11. Límites reales que quedan (léase antes de asumir nada como cerrado)

- **Nada de esto se ejecutó en la máquina Windows real del usuario ni
  con sus archivos FITS reales** (el M31 del transcript). Toda la
  validación de esta ronda es en este contenedor Linux sandboxed, con
  datos sintéticos y bajo Xvfb -- una verificación automatizada real,
  pero no la comprobación manual en el entorno de destino que el
  encargo describe en su "checklist de validación real".
- **Sin conectividad Gaia real** en este sandbox (el proxy del entorno
  probablemente bloquea el servicio) -- el crossmatch contra Gaia se
  verificó con mocks realistas (filtrado por radio angular real) y con
  el mecanismo de manejo de errores heredado (`crossmatch_gaia_safe`),
  probado forzando que la llamada de red real lance una excepción, no
  con una consulta genuina a `gaia.esac.esa.int`.
- **El plate solving no es "blind solving"**: si un FITS no trae ni
  puntero aproximado en el header ni el usuario lo introduce, falla
  honestamente en vez de resolver -- esto es alcance declarado, no un
  defecto, pero es una limitación real frente a astrometry.net/ASTAP.
- **El plate solving no se probó contra imágenes astronómicas reales**
  (rayos cósmicos, píxeles calientes, PSF variable, campos muy
  poblados o muy distorsionados) -- solo contra campos sintéticos de
  estrellas gaussianas limpias.
- **`IdentificationState.TRANSIENT_CANDIDATE`/`MOVING_SOURCE_CANDIDATE`**
  siguen sin ser producidos por ningún código real (hallazgo ya
  documentado en la Fase de diagnóstico, no abordado esta ronda --
  el encargo pidió explícitamente no añadir motores nuevos todavía).
- **Objetivo 6 del encargo (ruta de salida para TODAS las operaciones
  que producen archivos) solo se abordó parcialmente**: fotogramas
  maestros y la copia de FITS con WCS resuelto ya tienen selector de
  ruta real; no se hizo una auditoría sistemática del resto (p. ej.
  `ApplyCalibrationDialog` hoy solo crea una ventana en memoria, no
  guarda a disco todavía; la reducción de sesión de LIGHTS ya tenía su
  propio selector desde la Fase 10.1).
- **El resaltado del tutorial asume el layout de docks por defecto**:
  si el usuario mueve, flota o cierra un panel, ese paso puede no
  resaltar nada (degradación seguro -- nunca señala un lugar
  equivocado -- pero la guía se vuelve solo texto en ese caso).
- **No se generó ni probó un `.exe` de Windows con estos cambios** --
  el empaquetado (Fase 9) es anterior a esta ronda y no se ha
  reconstruido; estas funciones nuevas solo se ejecutaron como código
  Python fuente.
