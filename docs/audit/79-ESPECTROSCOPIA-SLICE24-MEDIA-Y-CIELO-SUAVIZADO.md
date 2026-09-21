# Informe 79 — Espectroscopía slice 24: extracción "media" + cielo suavizado (§3, §5)

Continuación del informe 78. Cierra las dos piezas concretas que
faltaban de §3 ("falta el modo media explícito") y §5 ("falta ajuste
polinómico suave explícito") -- la parte de visualización de ambas
secciones ya la cerró el overlay 2D del slice 17.

## Cambios

- `trace.py`: `extract_mean` (nuevo) -- reutiliza `extract_sum` al 100%, solo reescala flujo/incertidumbre ya calculados por el ancho nominal de apertura (total -> medio por píxel), nunca recalcula la extracción.
- `trace.py`: `estimate_sky_background` gana `smooth_degree`/`smooth_sigma_clip` -- ajuste polinómico real con rechazo iterativo sigma-clip sobre el nivel de cielo YA estimado por columna (mismo patrón ya usado para la traza en `trace_spectrum`, reutilizado explícitamente, no reimplementado). Puede rellenar columnas sin evidencia directa con un valor real interpolado. `extract_sum`/`extract_optimal`/`extract_mean` ganan `sky_smooth_degree` para activarlo.
- `registry.py`: `spectroscopy.trace` cambia el parámetro `optimal_extraction` (bool) por `extraction_method` (choice: suma simple / óptima / media) y añade `sky_smooth_degree` (int, 0=desactivado).

## Validación

- `ruff check`: limpio.
- `tests/unit/spectroscopy/test_trace.py` (+4 tests): `extract_mean` == `extract_sum`/ancho nominal exactamente; suavizado recupera un gradiente de cielo lineal conocido y reduce el ruido columna a columna frente a la estimación directa; falla honestamente si no hay evidencia suficiente para el grado pedido; `extract_sum` propaga el suavizado correctamente.
- `tests/unit/qt_app/test_registry.py` (+2 tests, 1 actualizado por el renombrado de parámetro): modo media real coincide con suma/ancho nominal; suavizado real se refleja en el resumen.
- Suite unitaria completa: **1031 passed** (antes: 1025).
- Suite de humo GUI completa: **189 passed** (sin cambio -- ningún test de humo tocaba el parámetro renombrado).
- Validación real sobre `Vega_1sec_1x1__frame6.fit` (mismo clic real y=602.0 ya usado en slices anteriores): modo "media" real y modo "suma + cielo suavizado grado 2" corren ambos de extremo a extremo sin excepciones, con S/N reales coherentes (294.5 y 292.2).

## Qué queda fuera

`spectroscopy.multiaperture`/`spectroscopy.extended_extraction` siguen sin el modo "media" ni el suavizado de cielo (solo `spectroscopy.trace`, el flujo principal de un único objeto) -- extenderlo a los otros dos procesos queda fuera del alcance mínimo de este slice, mismo motor ya reutilizable sin cambios cuando se haga. Siguiente: §2 (edición de traza en GUI) y §25 (comparación con templates).
