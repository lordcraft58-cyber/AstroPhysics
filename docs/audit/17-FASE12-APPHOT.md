# AstroPhysics Suite — Fase 12: cierre del núcleo de `apphot`

Tercer bloque del orden de prioridad acordado (`CCDRED → análisis de imagen →
fotometría → astrometría → tablas/catálogos → espectroscopía`). Cierra las dos
limitaciones más importantes que `13-IRAF-CAPABILITY-MAP.md` §3 señalaba en
`photometry.aperture`: la selección de fuente fija al centro de la imagen, y la
ausencia total de una calibración fotométrica real (el punto cero era siempre una
constante introducida a mano, nunca ajustada contra datos).

## 1. Selección de fuente a clic

`photometry.aperture` pasa de `requires_picking=None` (fijo en el centro de la
imagen) a `requires_picking=1`: al pulsar Aplicar, un único clic marca la posición
de la fuente -- mismo mecanismo genérico de selección de posiciones que ya
construyó la Fase 9.6 §8, sin ningún código de interacción nuevo. Renombrado en el
explorador a "Fotometría de apertura (clic)" para que el cambio sea visible sin
tener que leer la descripción.

## 2. Enhebrado de WCS real hasta los procesos (`ImageView.wcs`)

Requisito previo para calibrar contra un catálogo real: hasta ahora `ImageView`
solo guardaba el array de píxeles, nunca el WCS del FITS de origen, así que ningún
proceso podía saber la posición celeste de nada. `ImageView` gana un atributo
`wcs` (el objeto `astropy.wcs.WCS` real cargado por `open_fits`, `None` si el
archivo no tenía uno), y `main_window._start_process_worker` inyecta
`params["_wcs"]` antes de lanzar cualquier proceso -- disponible para
`photometry.zeropoint` ahora, y reutilizable sin cambios por astrometría en la
fase siguiente.

## 3. `astrophysics_suite/photometry/calibration.py` -- `fit_zeropoint`

Equivalente propio de la parte de calibración de `apphot`/`photcal`: cada estrella
de referencia aporta un punto cero individual (`catalog_mag - instrumental_mag`);
el resultado es la mediana robusta de esos puntos cero con rechazo iterativo
sigma-clip (MAD) de outliers -- nunca una media simple, que una sola estrella
variable o un cruce erróneo con el catálogo bastaría para desviar. 6 tests
unitarios (`tests/unit/photometry/test_photometric_calibration.py`): recuperación
exacta de un desplazamiento constante conocido, rechazo verificado de una estrella
con un punto cero individual muy distinto del resto, incertidumbre que se reduce
con más estrellas, y los casos límite (una sola estrella, longitudes distintas,
entrada vacía).

## 4. `photometry.zeropoint` -- calibración real contra Gaia DR3

Nuevo proceso, `requires_picking=0` (número ilimitado de estrellas de referencia,
clic derecho para terminar). Por cada posición marcada:

1. Fotometría de apertura instrumental real (`aperture_photometry`, el mismo motor
   que ya usa `photometry.aperture`, con punto cero 0 para obtener la magnitud
   instrumental cruda).
2. Conversión píxel -> cielo con el WCS real de la imagen activa
   (`wcs.celestial.all_pix2world`) -- si la imagen no tiene WCS, el proceso lo dice
   explícitamente (`ValueError` claro) en vez de fingir una posición.
3. Consulta real a Gaia DR3 (`catalogs.gaia.query_gaia_neighbors`, el mismo motor
   ya probado que usa el Discovery Engine -- nunca lanza, se degrada a lista vacía
   si Gaia no está disponible) y emparejamiento por vecino más cercano dentro del
   radio de búsqueda.
4. Cada estrella con una fotometría válida y un emparejamiento Gaia válido aporta
   un par (magnitud instrumental, magnitud de catálogo) a `fit_zeropoint`.

Cada posición marcada que no pudo procesarse (flujo neto negativo, sin WCS válido
en ese punto, sin fuente Gaia cercana, fuente sin magnitud G) se reporta como una
línea de log explicando por qué, nunca se descarta en silencio. Si ninguna
posición pudo emparejarse, el proceso falla con un mensaje claro en vez de
devolver un punto cero fabricado de la nada.

## 5. Verificación

23 tests de lógica pura en `tests/unit/qt_app/test_registry.py` (7 nuevos:
selección a clic de `photometry.aperture`, y el flujo completo de
`photometry.zeropoint` con `query_gaia_neighbors` sustituida por un doble
mockeado -- sin red -- que verifica que el punto cero recuperado coincide con uno
conocido de antemano, más los casos de error: sin posiciones, sin WCS, sin ningún
emparejamiento Gaia). 2 tests de humo GUI nuevos en
`tests/gui_smoke/test_qt_app_zeropoint_smoke.py`: flujo completo de clic real
sobre una imagen con WCS real (`astropy.wcs.WCS` real, no simulado) contra Gaia
mockeada, con el hilo de fondo real de principio a fin; y el caso sin WCS
fallando con un mensaje que nombra el problema real.

Suite completa verde en ambos entornos tras esta fase: 384 tests en el entorno con
PySide6 (`aps-gui`), 330 en el entorno sin GUI (`aps-test`), más `ruff` limpio en
los 8 archivos nuevos/tocados.

## 6. Qué queda del bloque `apphot` (documentado, no oculto)

Dos capacidades siguen sin cerrar, ninguna bloquea el resto del taller:

- **Ajuste de curva de crecimiento / radio óptimo**: `aperture_photometry` ya
  soporta varios radios en una sola llamada (curva de crecimiento cruda), pero no
  hay ningún ajuste que recomiende un radio óptimo a partir de esas medidas.
- **Detección automática de fuentes como paso previo interactivo**: el motor
  (`detect_point_sources`, DAOStarFinder real) existe y ya lo usa el Discovery
  Engine, pero `photometry.aperture`/`photometry.zeropoint` siguen dependiendo
  100% del clic manual del usuario -- no hay un botón "detectar automáticamente"
  que proponga posiciones candidatas antes de marcarlas.

Ninguno de los dos era necesario para que la calibración fotométrica real
funcionara de verdad, que era el objetivo de esta fase; quedan documentados aquí
para una fase posterior si se decide que hacen falta.
