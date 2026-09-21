# Informe 58 — Espectroscopía slice 4: velocidad radial multi-línea, correlación cruzada y corrección heliocéntrica/baricéntrica

Continuación de los informes 55-57. Cierra la tarea de tablero **#96 —
"Espectroscopía slice 4: velocidad radial multi-línea + correlación cruzada
+ corrección heliocéntrica/baricéntrica"**, cuatro secciones del encargo
original: §58 (correlación cruzada), §59 (velocidad radial multi-línea, "no
depender de una sola línea"), §60 (corrección heliocéntrica/baricéntrica) y
§61 (eje de velocidad, convención clásica/relativista explícita).

## 1. Doppler de una línea + eje de velocidad (§61)

`astrophysics_suite/spectroscopy/radial_velocity.py` (nuevo) --
`velocity_from_wavelength_shift()`: fórmula clásica
(`v = c*(lambda_obs/lambda_rest - 1)`) por defecto, o relativista (fórmula
SR de corrimiento Doppler longitudinal) con `relativistic=True` -- la
convención es siempre un parámetro explícito, nunca una elección oculta, tal
como pide el encargo. Funciona igual sobre un escalar (una medida de línea)
o un array completo (un eje de longitud de onda convertido a velocidad para
el visor 1D), sin una función separada para cada caso.

## 2. Velocidad radial multi-línea, con dispersión explícita (§59)

`measure_multi_line_radial_velocity()` mide cada línea de un conjunto dado
**independientemente** (nunca depende de una sola, verbatim del encargo) vía
`lines.measure_line()` ya existente, calcula la velocidad de cada una por
separado, y combina solo las que de verdad se pudieron medir -- una línea
fuera de rango o sin señal se omite, nunca se rellena con un valor inventado
(`MultiLineRVResult.n_lines_used` puede ser menor que `n_lines_requested`,
y el consumidor lo ve explícitamente).

La combinación es la media de las velocidades por línea, con la
**desviación estándar entre líneas como señal de fiabilidad explícita**
(`velocity_dispersion_km_s`) -- una dispersión grande avisa de una
identificación o calibración dudosa, exactamente lo que pide el encargo en
vez de esconderlo detrás de un único número. **Limitación documentada, no
oculta**: `lines.measure_line()` no propaga todavía una incertidumbre de
centroide por línea, así que `LineVelocityMeasurement.velocity_uncertainty_
km_s` es honestamente `None` siempre -- la combinación usa el error estándar
de la dispersión real entre líneas (`dispersión / sqrt(n)`) en vez de una
media ponderada por incertidumbres que no existen todavía.

## 3. Correlación cruzada contra una plantilla (§58)

`cross_correlate_radial_velocity()`: búsqueda directa en rejilla de
velocidad (no basada en FFT/rejilla log-lambda -- limitación documentada en
el propio docstring, adecuada para el rango/resolución de este dominio, no
para precisión sub-km/s profesional). Para cada velocidad de prueba,
interpola la plantilla sobre la rejilla observada bajo el corrimiento
Doppler correspondiente y mide la correlación de Pearson dentro del solape
real -- `np.interp(..., left=nan, right=nan)`, nunca una extrapolación
plana más allá de los datos reales de ninguna de las dos series.

Una velocidad de prueba sin solape útil queda `NaN` en `correlation`, nunca
`0.0` -- una correlación 0.0 real (formas descorrelacionadas) y una
ausencia de datos son informaciones distintas, y confundirlas escondería
justo la fiabilidad que hay que poder juzgar. `n_overlap_points` en el pico
deja ver si la mejor velocidad se apoya en pocos puntos.

Refinamiento subpíxel por interpolación parabólica alrededor del pico --
mismo estilo numérico que `wavelength.reidentify_wavelength_solution`
(Fase 15), reutilizado por consistencia en vez de reinventado.

## 4. Corrección heliocéntrica/baricéntrica real (§60)

`astrophysics_suite/spectroscopy/heliocentric.py` (nuevo) --
`compute_barycentric_correction()` usa `astropy.coordinates.SkyCoord.
radial_velocity_correction` (efemérides JPL vía astropy), la implementación
estándar y validada de la comunidad, **no una fórmula propia reinventada**.

Verbatim del encargo (§60): *"nunca asumiendo coordenadas desconocidas"* --
por eso RA/Dec del objeto, instante de observación y longitud/latitud/altura
del observatorio son **todos obligatorios, sin ningún valor por defecto**
(ni "geocentro", ni una ubicación "típica"): sin ellos, la función falla en
vez de fingir un dato que no se dio. La corrección se mantiene como un dato
SEPARADO de la velocidad observada -- `apply_barycentric_correction()` es
la única función que las combina, nunca ocurre dentro de la medición de
velocidad radial en sí.

Validado contra hechos astrofísicos reales, verificables sin necesitar un
valor de referencia hardcodeado: la magnitud nunca supera la velocidad
orbital terrestre (~29.8 km/s) más una pequeña componente de rotación
(<0.5 km/s); las correcciones baricéntrica y heliocéntrica difieren en como
mucho unas décimas de m/s (el arrastre del Sol por Júpiter etc.); el signo
se invierte aproximadamente cada seis meses para un objetivo fijo; el
resultado es determinista para las mismas entradas.

## 5. GUI

`qt_app/spectroscopy/radial_velocity_dialog.py` (nuevo, menú
Espectroscopía -> "Medir velocidad radial..."): elige un conjunto de líneas
(Balmer/Ca II H&K/Na D/nebulares -- reutilizando los catálogos de
`line_catalog.py` de la slice 2), ajuste de continuo configurable, mide
sobre la fila central de la imagen activa (misma convención que
`wavelength_fit_dialog`/`combine_spectra_dialog`) usando la calibración en
longitud de onda ya ajustada de la ventana -- exige que exista una
calibración antes de abrir el diálogo, igual que "Guardar espectro
calibrado...". Muestra la tabla por línea + el resumen combinado con
dispersión, y una sección separada y explícita de corrección
heliocéntrica/baricéntrica que exige RA/Dec/observatorio/instante reales
antes de calcular nada.

## 6. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| `tests/unit/spectroscopy/test_radial_velocity.py` (nuevo, 15 tests) | recupera una velocidad conocida multi-línea y por correlación cruzada, nunca inventa cuando no hay evidencia, distingue NaN (sin solape) de 0.0 (descorrelación real) |
| `tests/unit/spectroscopy/test_heliocentric.py` (nuevo, 9 tests) | magnitud físicamente sensata, determinismo, inversión de signo real a 6 meses, rechazo honesto de coordenadas/fecha inválidas |
| `tests/gui_smoke/test_qt_app_radial_velocity_smoke.py` (nuevo, 4 tests) | flujo de extremo a extremo con líneas de Balmer reales desplazadas por una velocidad conocida, corrección baricéntrica real aplicada, avisos honestos sin calibración/sin instante |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **877 passed** (antes del slice: 862 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **157 passed** (antes: 153) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (traza+extracción reales, eje de longitud de onda aproximado marcado como tal, corrección baricéntrica real) | corre sin excepciones; solo H-alpha cae dentro del rango aproximado (las otras 3 líneas de Balmer se omiten correctamente por estar fuera de rango, no se inventan) |

**Hallazgo real durante la construcción, corregido en el propio test, no
en el motor**: un centroide de momento simple (`lines.measure_line`, sin
ajuste Gaussiano) sobre una línea infrarresuelta (pocos píxeles por
sigma del perfil) se arrastra hacia el centro de la ventana de búsqueda
por puro ruido de las alas -- un sesgo real y conocido de ese método de
centroide, no un bug. Los tests de recuperación de velocidad se
ajustaron a un muestreo más fino (más puntos por línea) y una ventana de
búsqueda más ajustada, en vez de relajar la tolerancia sobre un motor
que en realidad funciona bien con un muestreo realista.

## 7. Qué queda fuera de este slice

Del encargo original de 79 secciones: ajuste Gaussiano/Voigt/multi-Gaussian
explícito para líneas y dobletes (§62 -- hoy la medición es por centroide
de momento, sin ajuste de perfil), identificación automática de líneas de
objeto tras calibrar (§21-22), objetos extendidos/nebulosas (§27),
corrección de flexión espectral entre exposiciones (§44), base de datos de
líneas telúricas (§46), magnitudes fotométricas desde espectro (§50),
soporte échelle (§52-54), y el bloque extendido de QC/informe/
reproducibilidad (§63-78).
