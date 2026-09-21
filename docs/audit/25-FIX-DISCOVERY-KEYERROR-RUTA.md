# Fix: Discovery fallaba siempre con `KeyError` de ruta

## 1. Síntoma reportado

En uso real (Windows, `python -m qt_app`), **todo** análisis de Discovery
fallaba con el mismo mensaje genérico en la barra de estado y la consola:

```
Descubrimiento falló: 'D:\Plan\Light\M 31\Light_M 31_300.0s_Bin1_20260915-063714_340deg_0095.fit'
```

Sin traceback, sin más contexto -- solo la ruta del archivo entre
comillas. El mismo patrón se repetía con distintos archivos y campos, lo
que apuntaba a un bug estructural (siempre el mismo tipo de fallo),
no a un problema puntual de un FITS concreto.

## 2. Diagnóstico

El formato exacto del mensaje -- una ruta entre comillas simples, sin
ningún texto adicional -- es la firma de `str(KeyError(x))` en Python:
`KeyError.__str__()` devuelve `repr(x)`, que para una cadena la envuelve
en comillas. Eso ya apuntaba a una búsqueda en diccionario fallida, no a
un error de E/S o de formato FITS.

Se siguió la cadena completa:

```
GUI (NewObservationDialog, QFileDialog.getOpenFileNames)
  -> MainWindow._start_discovery
  -> DiscoveryJob._run (services/discovery_service.py)
  -> build_observation (astrophysics_suite/io/fits_loader.py)
  -> run_generic_discovery (astrophysics_suite/discovery/pipeline.py)
```

`grep -rn "loaded_images\["` localizó un único punto de uso:

```python
# astrophysics_suite/discovery/pipeline.py:101
loaded = loaded_images[image_ref.path]
```

Y `build_observation` (antes del fix):

```python
loaded = {path: load_image(path, band=band, role=role) for path, band in images}
...
return observation, loaded
```

`loaded` queda indexado por la ruta **cruda** que pasó el llamador
(`path`, tal cual). Pero `image_ref.path` -- el valor con el que
`run_generic_discovery` busca cada imagen -- lo calcula `load_image` de
forma **independiente**, como `str(Path(path).resolve())`. Nada garantiza
que las dos cadenas coincidan carácter a carácter, aunque señalen al
mismo archivo:

- `Path(path).resolve()` convierte una ruta relativa en absoluta.
- En Windows, `QFileDialog.getOpenFileNames` (usado en
  `qt_app/candidates/new_observation_dialog.py`) devuelve rutas con `/`
  (la convención interna de Qt, no la nativa de Windows), mientras que
  `pathlib.Path.resolve()` normaliza a `\` -- **siempre** distintas en
  ese sistema operativo, para cualquier ruta.

## 3. Reproducción

```python
from pathlib import Path
rel = "legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py"
str(Path(rel).resolve()) == rel  # False -- confirma la brecha, en cualquier SO
```

Se escribió un test de regresión que reproduce el fallo real a través de
la cadena completa (`DiscoveryJob` -> `build_observation` ->
`run_generic_discovery`), usando una ruta relativa como entrada -- forma
determinista y multiplataforma de forzar que `Path(...).resolve()` cambie
el texto de la ruta (el mismo efecto que en Windows produce la diferencia
`/` vs `\` de Qt, sin depender de estar en Windows para probarlo):

`tests/unit/services/test_discovery_service.py::
test_discovery_job_completes_when_input_path_differs_from_its_resolved_form`

**Confirmado que reproduce el bug real**: ejecutado contra el código
anterior al fix, falla con exactamente el mismo patrón que reportó el
usuario:

```
AssertionError: Discovery falló con la ruta relativa (bug reproducido): '/tmp/.../field_relative.fits'
```

## 4. Causa raíz

`build_observation` derivaba dos valores del mismo `path` de entrada por
caminos distintos (la clave cruda del diccionario, y `ImageRef.path`
resuelto dentro de `load_image`) sin garantizar que coincidieran. El
`except Exception` genérico de `DiscoveryJob._run` (necesario para que
ninguna excepción real cruce la frontera hilo-de-fondo -> GUI sin
convertirse en un evento) capturaba el `KeyError` y lo mostraba con
`str(exc)`, que para un `KeyError` no da ninguna pista de dónde ocurrió.

## 5. Corrección

Un cambio mínimo, en el origen del problema: indexar `loaded_images` por
`ImageRef.path` (el mismo valor, ya resuelto, que usa `run_generic_discovery`
para buscar), no por la ruta cruda de entrada.

`astrophysics_suite/io/fits_loader.py::build_observation`:

```python
loaded_by_resolved_path: dict[str, LoadedImage] = {}
for path, band in images:
    loaded_image = load_image(path, band=band, role=role)
    loaded_by_resolved_path[loaded_image.image_ref.path] = loaded_image
...
return observation, loaded_by_resolved_path
```

Ahora las dos claves (la del diccionario y la de la búsqueda en
`run_generic_discovery`) se derivan del **mismo** valor
(`loaded_image.image_ref.path`), eliminando la posibilidad estructural de
que diverjan -- no un `try/except` alrededor de la búsqueda, ni un
`.get()` con valor por defecto que ocultaría el error de verdad si algún
día sí hubiera dos rutas distintas.

No se tocó `run_generic_discovery` ni `load_image`: el contrato de
`loaded_images` ("mapea `ImageRef.path` -> `LoadedImage`", ya documentado
en el docstring de `run_generic_discovery`) siempre fue ese; el bug
estaba en que `build_observation` no lo cumplía.

## 6. Tests

- `tests/unit/io/test_fits_loader.py::
  test_build_observation_indexes_loaded_images_by_resolved_path_not_raw_input`
  (nuevo) -- ruta relativa, verifica `image_ref.path in loaded`.
- `tests/unit/io/test_fits_loader.py::test_build_observation_from_real_files`
  (corregido) -- la aserción asumía que el diccionario se indexaba por la
  ruta cruda del test (coincidencia casual en un entorno de test Linux sin
  symlinks ni rutas relativas); ahora verifica el contrato real
  (`loaded[image_ref.path]` para cada `image_ref`).
- `tests/unit/services/test_discovery_service.py::
  test_discovery_job_completes_when_input_path_differs_from_its_resolved_form`
  (nuevo) -- reproduce el fallo real a través de la cadena completa
  (`DiscoveryJob`), confirmado que falla sin el fix y pasa con él.
- `tests/unit/services/test_discovery_service.py::
  test_discovery_job_reaches_known_and_unmatched_with_real_wcs_and_mocked_gaia`
  (nuevo) -- "Discovery con WCS válido": FITS con WCS TAN real (astropy),
  Gaia mockeado en el punto de entrada real (`query_gaia_neighbors`),
  confirma que se alcanzan `KNOWN` (estrella emparejada) y `UNMATCHED`
  (estrella sin fuente Gaia cercana) a través de la cadena completa.
- `tests/unit/services/test_discovery_service.py::
  test_discovery_job_does_not_crash_when_gaia_service_call_raises`
  (nuevo) -- "no rompe si Gaia no está disponible": simula el fallo de
  red real dentro del `try/except` que YA existe en
  `crossmatch_gaia_safe` (parcheando `Gaia.launch_job`, no sustituyendo
  el manejo de errores por uno artificial), confirma que Discovery
  completa degradando a `UNMATCHED`.
- `tests/integration/test_generic_discovery_pipeline.py::
  test_run_generic_discovery_end_to_end` (ya existía, sin cambios) --
  "Discovery sin WCS": confirma que sin WCS ninguna coordenada se
  inventa, todos los candidatos caen honestamente en `DISCOVERY_REVIEW`.

Suite completa: **368 tests pasan** en el entorno sin GUI (`aps-test`,
+4 sobre el estado anterior a este fix), 0 fallos.

## 7. Hallazgo honesto sobre los 7 estados de `IdentificationState`

El encargo pedía diferenciar `KNOWN`, `KNOWN_VARIANT`, `UNMATCHED`,
`ANOMALOUS`, `TRANSIENT_CANDIDATE`, `MOVING_SOURCE_CANDIDATE` y
`DISCOVERY_REVIEW`. Verificado contra el código real (no asumido):

- **`KNOWN`, `UNMATCHED`, `DISCOVERY_REVIEW`**: los únicos tres que
  `run_generic_discovery` (el pipeline que usa "Nueva observación" de la
  GUI) puede producir hoy -- vía `classify_against_gaia_neighbors`
  (`astrophysics_suite/catalogs/gaia.py`). Cubiertos exhaustivamente
  (`tests/unit/catalogs/test_gaia.py`, lógica pura) y ahora también de
  extremo a extremo (tests nuevos arriba).
- **`KNOWN_VARIANT`, `ANOMALOUS`**: solo los asigna
  `astrophysics_suite/models/legacy_adapter.py` -- el adaptador que
  traduce filas del pipeline **heredado** `discovery_scan_observation()`
  (Discovery Workspace v57, no `run_generic_discovery`) al contrato
  tipado. No forman parte de la ruta que ejecuta hoy "Nueva observación".
- **`TRANSIENT_CANDIDATE`, `MOVING_SOURCE_CANDIDATE`**: no los asigna
  ningún código real en el repositorio -- solo existen como valores del
  enum. `astrophysics_suite/models/temporal.py` los menciona en un
  comentario como pregunta abierta ("¿lo decide la orquestación...?"),
  sin resolver.

No se fabricó una prueba que aparente que `run_generic_discovery`
diferencia los 7 estados -- sería exactamente el tipo de "estado
aparentemente correcto" que el encargo pidió evitar. Esto es una brecha
real y preexistente (unificar el pipeline heredado con el genérico,
documentada desde la Fase 4/6), no algo introducido ni resuelto por este
fix.
