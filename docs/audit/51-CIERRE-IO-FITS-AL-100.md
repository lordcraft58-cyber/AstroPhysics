# 51 — Cierre de IO/FITS al 100%

Primer motor del P0 del usuario, siguiendo su propio criterio: *"Yo
empezaría ahora por cerrar IO/FITS al 100%, y no tocaría nada del
siguiente motor hasta que ese primero tenga su checklist completo y
tests reales."*

La auditoría previa (respuesta a "¿qué hace io/fits?") encontró cuatro
huecos reales. Este informe los cierra los cuatro.

## 1. La lectura de FITS ya no vive en el monolito legacy

**El hueco**: `io/fits_loader.py` importaba `load_fits`/`sha256_file` de
`legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py` como "dependencia
transicional documentada". Es decir: el núcleo de la lectura de píxeles
de TODO el programa -- manejo de cubos, decisión de memmap, WCS, escala
de placa -- seguía en el archivo de 14.000 líneas que la arquitectura
nueva decía estar sustituyendo.

**Lo hecho**: `astrophysics_suite/io/fits_reader.py` trae `load_fits`,
`FitsImage`, `sha256_file`, `AmbiguousCubeError`, `select_cube_plane` y
`probe_fits_shape`. `astrophysics_suite/io/` ya no importa el monolito
para leer un solo píxel.

Se conserva el comportamiento observable **exacto**, con dos diferencias
deliberadas y declaradas:

- **Se cae el lector mínimo de respaldo para "astropy ausente"**.
  astropy es dependencia dura declarada del producto y todo
  `astrophysics_suite/` ya la importa sin condiciones; ese segundo
  parser de FITS escrito a mano no sabía leer cubos ni WCS. Era código
  muerto con riesgo real, no una capacidad.
- **La escala por cabecera la calcula `instruments/optics.py`**
  (`pixel_scale_from_wcs_header`), que pasa a ser el único sitio del
  proyecto con esa lógica. Era la **tercera** implementación de la misma
  cuenta (las otras dos se unificaron en el informe 50).

**Lo que autoriza el cambio**: `tests/regression/
test_fits_reader_matches_legacy.py` compara los dos lectores **campo a
campo, con los píxeles byte a byte**, sobre FITS sintéticos (2D simple,
WCS real, uint16 con BZERO, cubos, cubo ambiguo, plano de vista rápida)
y sobre los **tres archivos reales de M 31 del usuario** -- 3008×3008
uint16 de una ASI533MC Pro con BZERO, que es justo el caso que desactiva
memmap. No basta con que el lector nuevo funcione: tiene que dar lo
mismo que el que llevaba usándose todo el proyecto.

Hallazgo real durante la migración: la `AmbiguousCubeError` nueva es una
**clase distinta** de la del monolito. Ambas siguen siendo `ValueError`,
así que cualquier `except ValueError` existente las atrapa igual, y la
GUI la importa desde `io.fits_loader` (que reexporta la nueva) -- pero
el test lo deja asertado explícitamente en vez de que sea un accidente
afortunado.

## 2. XISF se lee nativo, sin archivo temporal ni pérdida de cabecera

**El hueco**: cada XISF se decodificaba y se **volcaba a un FITS
temporal en disco** solo para poder releerlo con `load_fits`. Además, al
convertir la cabecera a tarjetas FITS, las claves no representables se
descartaban con un `continue` silencioso.

**Lo hecho**: `fits_image_from_arrays` construye la `FitsImage` desde
píxeles y cabecera ya en memoria, aplicando **el mismo** motor de cubos,
WCS y escala que un FITS -- no una segunda implementación para el otro
formato. Sin tocar disco. Y la cabecera devuelta **conserva todas las
claves del XISF original**: el recorte a tarjetas FITS ocurre solo en
una copia interna y efímera que se usa únicamente para derivar el WCS.

## 3. La escala de placa ya se contrasta en vez de discrepar en silencio

Había dos formas de saber la escala de un campo -- deducirla de la
óptica declarada (informe 50) o leerla de la astrometría de la cabecera
-- y **nada comprobaba que coincidieran**.
`instruments/optics.py::compare_pixel_scales` las contrasta y expone la
diferencia relativa. Una discrepancia real significa que una de las dos
miente: focal mal declarada, binning no contado, un demosaico que cambió
el tamaño, o un WCS heredado de otra imagen.

Sobre los datos reales del usuario: la astrometría de su cabecera da
**1.0339 "/px** y su óptica **1.0355 "/px** -- concuerdan al 0.15%.

## 4. El WCS y el punto cero sobreviven a cerrar la aplicación (P0 nº9)

**El hueco**, que es literalmente el punto 9 del P0 del usuario: un WCS
ajustado a mano o construido desde la óptica, y el punto cero
fotométrico real de una imagen, solo vivían en memoria
(`services/session_state.py`) y **morían al cerrar**. La sesión guardada
no los llevaba.

**Lo hecho**:

- `WCSSolution` y `ZeropointFit` ganan `to_dict`/`from_dict` sin pérdida
  -- junto al tipo, como ya hacía `Candidate`, no escondido dentro del
  exportador. La matriz CD (un `ndarray`, no serializable) viaja como
  listas de float y vuelve idéntica; la máscara de sigma-clip del punto
  cero también.
- `session_export` sube a `schema_version = 2` y **sigue leyendo las
  sesiones v1** ya guardadas por el usuario. Lo que se rechaza es una
  versión FUTURA desconocida (adivinar hacia adelante), no una anterior
  que sí sabemos interpretar. Una v1 carga las calibraciones vacías,
  nunca inventadas.
- La GUI las guarda al salvar y las restaura al abrir.

Validado de extremo a extremo con un light real: WCS construido desde la
óptica → sesión guardada → reabierta → el mismo punto del cielo bajo la
misma esquina de la imagen.

## Tests

- `tests/regression/test_fits_reader_matches_legacy.py` (10): la prueba
  que autoriza la migración. Los 3 tests sobre archivos reales se saltan
  limpiamente si no existe `ASTROPHYSICS_REAL_FITS_DIR` -- los archivos
  del usuario pesan demasiado para versionarlos, pero cuando están son
  el contraste que de verdad vale.
- `tests/unit/io/test_session_export.py` (+3): ida y vuelta real del WCS
  y del punto cero (comprobando que el WCS restaurado **apunta al mismo
  sitio del cielo**, no solo que los números coincidan), calibraciones
  ausentes que cargan vacías, y compatibilidad con sesiones v1.
- Los 39 tests de `tests/unit/io/` siguen pasando con el lector nuevo y
  con XISF nativo, sin tocar ninguno.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **736 passed, 24 skipped, 1 xfailed** (antes: 726) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **142 passed** |

## Lo que queda fuera de IO/FITS, dicho claramente

- **Escritor XISF.** El programa lee XISF con lector propio pero escribe
  siempre en FITS. Sigue siendo un motor nuevo, no un cable suelto.
- **El resto de dependencias del monolito legacy.** `io/` ya está
  limpio, pero siguen importándolo `detection/point_sources.py`,
  `photometry/quality.py`, `catalogs/`, `physics/`, `temporal/`,
  `evidence/`, `anomaly/` y `artifacts/`. Cada una es la migración de
  SU motor, no de éste -- y el orden que propone el usuario las va
  recorriendo. Comprobado de paso que ninguna hace `isinstance` contra
  la `FitsImage` del monolito (solo acceden a atributos, y Discovery la
  muta en sitio: por eso la clase nueva tampoco es `frozen`), así que
  el cambio de tipo no rompe nada.

## Cambio de motor

IO/FITS cerrado. Siguiente en el orden del propio usuario: **Reduction**.
