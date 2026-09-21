# AstroPhysics Suite — Fase 16: cierre del bloque `apphot`

Tras completar el recorrido por los seis bloques del orden de prioridad
acordado (`CCDRED → análisis de imagen → fotometría → astrometría →
tablas/catálogos → espectroscopía`), esta fase retoma los dos huecos que
`13-IRAF-CAPABILITY-MAP.md` documentaba como `PENDIENTE` dentro de `apphot`
-- bloque que ya tenía su núcleo cerrado desde la Fase 12, pero no estaba
completo. Se prioriza sobre los pendientes de bloques posteriores (astrometría,
tablas, espectroscopía) porque `apphot` va antes en el orden acordado y sus
huecos son de menor riesgo/alcance que los de esos otros bloques (que son
deliberadamente pendientes: "blind solving", unificación profunda de tipos,
abstracción de catálogo con más de un proveedor).

## 1. Ajuste real de curva de crecimiento / radio óptimo

`aperture_photometry` ya medía en varios radios en una sola llamada (la
"curva de crecimiento cruda" de IRAF `phot`), pero nadie ajustaba esa curva
ni recomendaba un radio. `fit_curve_of_growth`
(`astrophysics_suite/photometry/aperture.py`) cierra ese hueco:

- Ajusta el flujo neto medido en función del radio a un modelo de
  saturación monótono `F(r) = F_inf · (1 - e^{-(r/r0)^p})` vía
  `scipy.optimize.curve_fit` -- tres parámetros libres (flujo asintótico,
  radio de escala, índice de forma), con cotas físicas (todos positivos) y
  sin necesidad de una forma funcional más compleja: el objetivo no es
  modelar la PSF exactamente, sino capturar la forma de saturación real de
  la curva medida.
- El radio óptimo recomendado **no se extrapola del ajuste** -- es el radio,
  entre los realmente medidos, que maximiza la señal/ruido ya calculada por
  `aperture_photometry`. Este es el criterio estándar de "apertura óptima"
  de una curva de crecimiento (p. ej. Howell, *Handbook of CCD Astronomy*,
  cap. 5): más allá de cierto radio, la apertura sigue sumando ruido de
  cielo sin sumar señal significativa, así que la S/N baja aunque el flujo
  total siga creciendo.
- `GrowthCurveFit` expone también `flux_fraction_at_optimal` (qué fracción
  del flujo asintótico ajustado captura el radio recomendado) y
  `rms_residual` (calidad del ajuste), para que el usuario pueda juzgar la
  recomendación en vez de aceptarla a ciegas.

En la GUI, `photometry.aperture` gana la casilla opcional "Ajustar curva de
crecimiento (radio óptimo)": cuando está activa, mide en 8 radios adicionales
generados alrededor del radio de apertura elegido (acotados para no salir del
anillo de cielo), ajusta la curva, y añade la recomendación como línea de
diagnóstico -- **la medida principal reportada sigue siendo la del radio que
eligió el usuario**, sin cambios de comportamiento en el flujo ya probado
desde la Fase 12. Además exporta una `Table` (radio, flujo neto, S/N) vía el
mismo mecanismo genérico de la Fase 14.

## 2. Detección automática conectada como paso previo interactivo

El motor de detección (`DAOStarFinder` real, vía
`detection/point_sources.py`) ya existía y ya lo usaba el Discovery Engine,
pero estaba desconectado de la fotometría interactiva -- el usuario solo
podía marcar posiciones a mano. `detect_point_sources_in_array` (nueva
función en el mismo módulo) reutiliza el mismo motor directamente sobre un
array en memoria, sin pasar por `LoadedImage`/`Detection` (que exigen
`observation_id`, banda y proveniencia -- pensados para el Discovery Engine,
no para "detectar unas posiciones para hacer clic por mí"): construye el
`FitsImage` legacy mínimo necesario y llama a `estimate_background` +
`detect_point_sources` (legacy), devolviendo `(x, y, flujo)` ordenado de más
a menos brillante.

`photometry.aperture` y `photometry.zeropoint` ganan una casilla "Detectar
automáticamente (omite clic)" + los mismos dos parámetros que ya aceptaba el
motor (`fwhm_px`, `threshold_sigma`), expuestos directamente en el
formulario -- no hay nada que ocultar tras "avanzado", son exactamente los
argumentos reales de `detect_point_sources_in_array`. Cuando está activa,
`MainWindow._run_with_auto_detected_points` (nuevo método) sustituye a
`_start_picking_then_run`: detecta, y usa las posiciones detectadas
directamente como `_picked_points` -- **la fuente más brillante** para
`photometry.aperture` (`requires_picking=1`) o **hasta 20** para
`photometry.zeropoint` (`requires_picking=0`, selección ilimitada), la
misma distinción que ya regía la selección manual, así que no hay lógica
nueva específica de cada proceso. Si no se detecta ninguna fuente por
encima del umbral, se informa en la barra de estado en vez de abrir una
selección vacía o fingir un resultado.

## 3. Verificación

Motor: `tests/unit/photometry/test_aperture.py` (4 pruebas nuevas --
`fit_curve_of_growth` recupera el flujo asintótico real y el radio óptimo
maximiza realmente la S/N medida sobre datos sintéticos de una estrella
gaussiana aislada con ruido; rechaza menos de 4 radios) y
`tests/unit/detection/test_point_sources.py` (2 pruebas nuevas --
`detect_point_sources_in_array` encuentra estrellas inyectadas, las ordena
de más a menos brillante, y devuelve lista vacía sobre un campo plano).

GUI: `tests/unit/qt_app/test_registry.py` (2 pruebas -- `photometry.aperture`
con `fit_curve_of_growth=True` añade la línea de diagnóstico y la tabla;
por defecto ambas casillas nuevas están desactivadas y no cambian el
resultado ya probado) y `tests/gui_smoke/test_qt_app_smoke.py` (3 pruebas de
humo con `QApplication`/hilo de fondo reales -- detección automática +
curva de crecimiento de extremo a extremo sin ningún clic simulado; aviso
claro sin fuentes por encima del umbral; `photometry.zeropoint` con
detección automática mide dos estrellas reales, las empareja contra Gaia
simulada, y reporta un punto cero correcto, todo sin clics).

Suite completa verde en ambos entornos tras esta fase: 416 tests en el
entorno con PySide6 (`aps-gui`, +10 sobre la Fase 15), 346 en el entorno sin
GUI (`aps-test`, +5), más `ruff --select F,E9` limpio en los 8
archivos nuevos/tocados.

## 4. Qué queda (ninguno de `apphot`)

Con esta fase, las 7 capacidades de la tabla de `apphot` en
`13-IRAF-CAPABILITY-MAP.md` quedan en `DISPONIBLE` -- ninguna `PENDIENTE`.
El siguiente bloque con pendientes reales según el orden de prioridad
acordado es `daophot` (selección automática de estrellas PSF, refinamiento
iterativo tipo `allstar`, diagnóstico de calidad de ajuste) -- ver la
siguiente fase.
