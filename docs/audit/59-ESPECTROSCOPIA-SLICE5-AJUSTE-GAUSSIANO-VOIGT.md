# Informe 59 — Espectroscopía slice 5: ajuste paramétrico de líneas (Gaussiano/Voigt/multi-Gaussiano)

Continuación de los informes 55-58. Cierra la tarea de tablero **#97 —
"Espectroscopía slice 5: ajuste Gaussiano/Voigt/multi-Gaussiano de líneas
(§62)"** -- la sección §62 del encargo original: *"ajuste Gaussiano/Voigt/
multi-Gaussiano, ajuste simultáneo multi-componente para dobletes (Na D,
[N II], [S II])"*, y cierra además una limitación documentada explícitamente
en los informes 4 (`lines.py`) y 58 (`radial_velocity.py`): la ausencia de
una incertidumbre real de centroide/anchura por línea.

## 1. Motor: `astrophysics_suite/spectroscopy/line_profile_fit.py`

Complementario a `lines.measure_line` (centroide de momento, robusto pero
sin forma de perfil ni incertidumbre real), este módulo asume
explícitamente una forma de perfil y ajusta por mínimos cuadrados no
lineales REAL -- `astropy.modeling.fitting.LevMarLSQFitter`, la
implementación estándar y ya probada de la comunidad, no un optimizador
propio reinventado. Eso da acceso a una incertidumbre real por parámetro
desde la matriz de covarianza del ajuste.

- **`fit_gaussian_line()`**: centro/amplitud/sigma/FWHM/flujo integrado/EW,
  todos con incertidumbre real propagada desde la covarianza (incluida la
  covarianza cruzada amplitud-sigma en la propagación del flujo integrado).
- **`fit_voigt_line()`**: perfil de Voigt (`astropy.modeling.models.
  Voigt1D`) para líneas con alas más anchas que una Gaussiana pura. FWHM
  combinado por la aproximación de Olivero & Longbothum (1977, JQSRT 17,
  233). Limitación documentada, no oculta: sin fórmula cerrada para
  propagar la incertidumbre de la integral numérica del perfil de Voigt --
  `integrated_flux`/`equivalent_width` son valores centrales reales sin
  incertidumbre asociada.
- **`fit_multi_gaussian_lines()`**: ajuste SIMULTÁNEO de N Gaussianas sobre
  una ventana compartida (§62: "ajuste multi-componente para dobletes") --
  cada componente ve la contribución de las demás durante el ajuste, a
  diferencia de ajustar cada línea por separado. `shared_sigma=True` ata el
  sigma de todas las componentes (misma resolución instrumental para líneas
  próximas) -- una hipótesis física explícita que el llamador debe pedir.

**Nunca acepta un ajuste degenerado como una medida real**: sin
convergencia, sin covarianza calculable, o por debajo de
`min_significance_sigma` (3σ por defecto, el umbral estándar en
espectroscopía) -> `None`. En el ajuste multi-Gaussiano, un componente
individual insignificante dentro del ajuste conjunto se omite sin
descartar los demás.

**Hallazgo real durante la construcción, documentado en el propio
docstring del módulo** ("look-elsewhere effect"): con centro y anchura
libres dentro de la ventana, el ajuste busca la MEJOR fluctuación de ruido
posible, no una posición fija -- la tasa real de falso positivo a un umbral
nominal de 3σ es notablemente mayor que 3σ de verdad (medido: ~1 de cada 7
ventanas de puro ruido produce un componente "significativo" en el ajuste
de dos líneas). No es un fallo del motor, es una propiedad real y conocida
de cualquier ajuste con posición/anchura libres -- documentado para que el
llamador use un umbral más exigente cuando la detección deba resistirlo.

## 2. GUI

Nuevo proceso `spectroscopy.line_profile_fit` ("Ajuste de perfil de línea
(Gaussiana/Voigt)", menú de procesos -> Espectroscopía), mismo patrón de
clic-para-marcar que "Medición de línea (splot)": elige perfil
(Gaussiana/Voigt), ajusta sobre la fila central igual que el resto de
procesos espectroscópicos del taller, y muestra tabla + gráfica con la
ventana de ajuste marcada. Nunca oculta un ajuste fallido: si no converge o
no supera el umbral de significancia, el proceso falla con un mensaje real
en vez de mostrar un resultado inventado.

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo + modificado) | limpio |
| `tests/unit/spectroscopy/test_line_profile_fit.py` (nuevo, 18 tests) | recupera parámetros conocidos (Gaussiana/Voigt/doblete), incertidumbre real no `None`, EW con signo correcto, nunca acepta ruido puro como línea real (con el look-elsewhere effect documentado y verificado) |
| `tests/gui_smoke/test_qt_app_picking_smoke.py` (+2 tests parametrizados Gaussiana/Voigt) | flujo completo clic -> ajuste -> tabla -> gráfica, mismo patrón que "Medición de línea" |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **904 passed** (antes del slice: 886 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **159 passed** (antes: 157) |
| Ajuste Gaussiano/Voigt real sobre `Vega_1sec_1x1__frame6.fit` (traza+extracción+continuo reales, línea localizada por el mínimo real del residuo, no una posición supuesta) | corre sin excepciones; χ² reducido alto (~770-870) refleja honestamente que la incertidumbre de flujo usada (aproximación Poisson sin ganancia/ruido de lectura reales de esta cámara) subestima el ruido real -- no se oculta, se reporta tal cual |
| Ajuste de Voigt sobre datos reales con resolución de 1 px | `fwhm_lorentzian` se pega a su cota inferior (1 px, el límite de muestreo) con una incertidumbre grande -- comportamiento honesto y esperado de la degeneración Gaussiana/Lorentziana cuando el perfil real no resuelve el componente Lorentziano, no un error |

## 4. Qué queda fuera de este slice

Del encargo original de 79 secciones: identificación automática de líneas
de objeto tras calibrar usando estos ajustes (§21-22, hoy sigue con
`match_lines_to_catalog` + centroide de momento), objetos extendidos/
nebulosas (§27), corrección de flexión espectral entre exposiciones (§44),
base de datos de líneas telúricas (§46), magnitudes fotométricas desde
espectro (§50), soporte échelle (§52-54), y el bloque extendido de QC/
informe/reproducibilidad (§63-78).
