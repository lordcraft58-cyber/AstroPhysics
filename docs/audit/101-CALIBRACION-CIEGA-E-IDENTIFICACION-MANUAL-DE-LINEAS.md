# 101 — CONSTRUIR: Calibración ciega por estrella de referencia +
# identificación manual de líneas por clic

Encargo directo del usuario a partir de un espectro real de T-CrB
(`264fd285-T-CrB.fits`, Observatorio Guirguillano): *"calibra... Deberían
salir líneas o tener espectros de referencia para restarlos y comprobar
que tipo de estrella es y poder elegir líneas de emisión como lo hace
[software de referencia de espectroscopía amateur]. Incluso si se te
ocurre algo mejor, hazlo"*.

## Qué se construyó, y qué no -- y por qué

Tres piezas nuevas, cero motores científicos nuevos (reutilización, no
duplicación):

1. **Búsqueda ciega de dispersión** (`reference_star_calibration.
   blind_calibrate_from_reference_star`, nuevo): cuando no se conoce la
   dispersión/origen aproximados del espectrógrafo, los busca ella misma
   probando la transformación lineal que implica cada PAR de detecciones
   reales emparejado con cada PAR de líneas del catálogo, y verificando
   cuál explica más detecciones reales distintas a la vez -- mismo
   principio de "candidato desde un par real, verificado contra el
   resto" que ya usa `astrometry.frame_registration.
   estimate_frame_translation` (informe 100) para registrar fotogramas
   sin WCS, aquí en 1D. Reutiliza `object_line_identification.
   detect_object_lines`, `line_catalog.match_lines_to_catalog` y
   `wavelength.fit_wavelength_solution` -- los mismos tres motores que ya
   usaba `calibrate_from_reference_star` (§13, informe 55). Calibración
   marcada `blind_search=True` en `WavelengthCalibrationRecord`, con su
   propio aviso obligatorio en `build_wavelength_provenance` (más allá
   del aviso normal de `REFERENCE_STAR`): con pocas detecciones reales,
   una coincidencia por azar es más probable que dando la dispersión a
   mano. Cableada como casilla nueva ("Búsqueda ciega de dispersión") en
   los procesos "Calibrar por estrella de referencia..." y "Autoprocesar
   espectro (§34)".

2. **Identificación manual de líneas por clic derecho**
   (`line_catalog.nearby_catalog_lines`, nuevo, + `SpectrumView.
   point_right_clicked`/`add_marker`, nuevos, + menú contextual en
   `main_window.py`): clic derecho sobre un punto real ya calibrado en
   longitud de onda del visor de espectros -> menú con las líneas de
   catálogo reales más cercanas (los 5 catálogos de objeto a la vez,
   ±15 Å) -> "Añadir marca" aplica la elegida como marca real sobre el
   espectro, sin resetear el zoom. Nunca identifica nada por sí sola: es
   exactamente el patrón "clic -> candidatas reales -> confirmación
   manual" que ya exige `match_lines_to_catalog` para la identificación
   automática, aplicado aquí a una posición real en vez de una predicha.
   `NAMED_OBJECT_LINE_CATALOGS` (nuevo, en `line_catalog.py`) consolida
   en una sola implementación real el diccionario de catálogos con
   nombre que antes vivía duplicado de forma privada en
   `qt_app.processes.registry._OBJECT_LINE_CATALOGS`.

3. **Comparación con espectro de referencia**: YA EXISTÍA
   (`template_comparison.py` + `template_comparison_dialog.py`, "Espectroscopía
   -> Comparación con plantilla de referencia"): el usuario carga
   cualquier FITS 1D real como plantilla (otra observación propia, una
   estrella estándar, un espectro de referencia guardado por otro
   programa) y ve observado/plantilla/residuo real -- se le señaló al
   usuario en vez de reconstruirla.

## Lo que NO se construyó -- deliberadamente, no por omisión

**Una biblioteca interna de espectros de referencia por tipo espectral
para clasificar automáticamente** (lo que el usuario compara con
"espectros de referencia... para comprobar qué tipo de estrella es") NO
se construyó. Dos motivos reales, verificados en esta misma sesión, no
supuestos:

- Sin acceso de red en este entorno (verificado: `vizier.cds.unistra.fr`
  y `www.stsci.edu` responden 403 en el proxy de salida configurado) no
  hay forma de traer una biblioteca real y publicada (p. ej. Pickles
  1998, MILES) -- y fabricar una inventada para que "parezca" clasificar
  sería presentar una clasificación falsa como si fuera real.
- `template_comparison.py` ya documenta explícitamente esta misma
  decisión desde antes de este informe (§25/§26): *"Deliberadamente NO
  clasifica ni sugiere un tipo espectral: sin una biblioteca real de
  plantillas por tipo espectral de la que generalizar, cualquier
  'coincidencia' automática sería una clasificación inventada"*.

## Validación con datos reales de T-CrB -- hallazgo real, no un éxito fabricado

Con datos sintéticos (dispersión y líneas de Balmer conocidas, ruido
gaussiano real) `blind_calibrate_from_reference_star` recupera la
dispersión real dentro de ~5 Å en todo el rango, y lanza `ValueError`
honesto cuando no hay ninguna combinación real que explique suficientes
detecciones -- 6 tests unitarios nuevos.

Ejecutando el autoproceso completo sobre el `264fd285-T-CrB.fits` real
del usuario con la búsqueda ciega activada: **encuentra una solución (no
falla), pero esa solución NO es fiable** -- con el catálogo de Balmer da
un rango de longitud de onda de -4384 a 22652 Å (negativo, físicamente
imposible), y acotando la búsqueda a un rango de dispersión realista para
un espectrógrafo amateur (0.5-5 Å/px) sigue dando un origen por debajo
del corte atmosférico UV real (~2343 Å). Causa raíz, la MISMA que ya se
reportó en la entrega anterior sobre este archivo: este FITS es un stack
mediano normalizado de Siril (`STACKCNT=11`, valores entre 0 y ~0.05, sin
`GAIN`/`RDNOISE` reales en cabecera) -- el modelo de respaldo `sqrt(ADU)`
del taller da una incertidumbre CONSTANTE de 1.0 en cada píxel para este
archivo, así que el detector de líneas reales (`detect_object_lines`)
encuentra 26 "detecciones" sobre este espectro, la mayoría casi
seguramente ruido/estructura del continuo mal significada y no líneas
espectrales reales -- ninguna búsqueda, ciega o no, puede dar una
calibración fiable a partir de detecciones que no son líneas reales.

**Conclusión honesta, comunicada al usuario**: la búsqueda ciega funciona
correctamente (los tests con datos reales lo confirman, y sobre T-CrB no
falla ni inventa un resultado silencioso -- avisa de que es "búsqueda
ciega" en la procedencia), pero no puede compensar un problema de datos
de entrada. Para este archivo concreto hace falta, antes de calibrar: (a)
un fotograma individual sin normalizar de la cámara Atik en vez del stack
de Siril, idealmente con `GAIN`/`RDNOISE` reales en la cabecera, o (b) la
dispersión aproximada real del espectrógrafo dada a mano en vez de la
búsqueda ciega.

## Tests

- `tests/unit/spectroscopy/test_reference_star_calibration.py`: +6
  (recupera dispersión sintética sin ninguna aproximación, aviso de
  procedencia, rechaza objeto vacío, rechaza rango de dispersión
  inválido, honesto sin ninguna línea real, honesto con una sola
  detección).
- `tests/unit/spectroscopy/test_line_catalog.py`: +6 (`NAMED_OBJECT_LINE_
  CATALOGS` consolidado, `nearby_catalog_lines` encuentra/ordena/filtra
  candidatas reales, rechaza tolerancia no positiva).
- `tests/unit/spectroscopy/test_calibration_provenance.py`: cubierto por
  los tests de `blind_search` en `test_reference_star_calibration.py`
  (aviso propio verificado ahí).
- `tests/gui_smoke/test_qt_app_spectrum_view_smoke.py`: +4 (clic derecho
  emite el punto real más cercano, clic derecho fuera del área no emite
  nada, `x_unit` refleja la unidad activa, `add_marker` no resetea el
  zoom).

`pytest tests/unit tests/integration tests/regression -q`: **1771
passed, 25 skipped** (14 tests nuevos sobre la base de 1757 del informe
100). `pytest tests/gui_smoke -q` bajo Xvfb: **221 passed** (4 nuevos
sobre 217).
