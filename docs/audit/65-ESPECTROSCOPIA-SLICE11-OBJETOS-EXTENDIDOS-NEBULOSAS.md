# Informe 65 — Espectroscopía slice 11: objetos extendidos/nebulosas (§27)

Continuación de los informes 55-64. Cierra el hueco explícitamente
señalado en los informes 62 §4/64 §4: hasta este slice, toda la
extracción espectral (`trace_spectrum`/`extract_sum`/`extract_optimal`,
`multiaperture.py`) asumía un objeto puntual con un centroide seguible
columna a columna -- nunca una región espacial ancha/plana definida
directamente por el usuario.

## 1. Motor: `astrophysics_suite/spectroscopy/extended_extraction.py`

- `SpatialRegion(row_start, row_end, label="")`: rango CERRADO por ambos
  extremos (documentado explícitamente para evitar la confusión con el
  slicing de Python) que describe una región espacial fija.
- `extract_extended_region(...)` construye una `TraceResult` SINTÉTICA de
  centro constante (nunca sigue ningún centroide) y reutiliza
  `trace.extract_sum` ya probado -- **nunca** `extract_optimal`.

### Por qué nunca extracción óptima aquí

`extract_optimal` (Horne 1986) asume que TODAS las columnas comparten un
único perfil espacial normalizado a un pico (`master_profile`). Esa
premisa no se sostiene para emisión extendida real, que puede ser plana,
multi-pico, o cambiar de forma a lo largo de la rendija -- usarla ahí
produciría una extracción sesgada sin ningún aviso. Documentado
explícitamente en el docstring del módulo, y el `ProcessDefinition` de la
GUI ni siquiera ofrece la opción.

### Validaciones reales añadidas (dos hallazgos durante la construcción)

1. **Región fuera de imagen silenciosamente "exitosa".** La primera
   versión no comprobaba los límites de la imagen: una región con
   `row_start`/`row_end` fuera de rango no lanzaba ningún error, solo
   devolvía un `ExtractedSpectrum` con todas las columnas inválidas
   (indistinguible de una región legítima sin señal). Corregido con una
   comprobación explícita de límites, igual disciplina que el
   `initial_center_px` de `trace_spectrum`.
2. **Ventana de cielo que solapa la propia región.** Una región de
   objeto extendido puede ser mucho más ancha que
   `DEFAULT_SKY_WINDOWS` (±10 px) -- si una ventana de cielo cae DENTRO
   de la región, el "cielo" medido incluiría flujo real del objeto,
   sesgando la resta de fondo sin ningún aviso. Rechazado explícitamente
   con un mensaje claro en vez de dejarlo pasar en silencio.

### Aclaración de contrato (no un bug, un hallazgo de diseño)

`sky_windows=()` NO es una forma de "omitir la resta de cielo": hereda el
comportamiento ya existente de `estimate_sky_background`/`extract_sum`
-- sin evidencia real de cielo, la columna entera queda inválida
(`NaN`), nunca se inventa un fondo de `0.0`. Si un objeto llena tanto la
rendija que no queda cielo limpio en ningún lado, este motor no puede
inventarlo: hace falta una exposición de cielo separada (fuera del
alcance de este slice). Un test de regresión fija este comportamiento
explícitamente para que nadie lo asuma al revés en el futuro.

- `extract_multi_region(...)` extrae varias regiones independientes
  (p. ej. núcleo vs. borde de una misma nebulosa) para resolverla
  espacialmente -- una región que falla se reporta con el motivo real sin
  detener el resto del lote, misma disciplina que `multiaperture.py`.

## 2. GUI: `qt_app/processes/registry.py` -- `spectroscopy.extended_extraction`

Wiring por el registro genérico de procesos (no un diálogo dedicado,
igual que `spectroscopy.multiaperture`): marca DOS clics por región (fila
inicial y fila final, en cualquier orden) -- clic derecho para terminar
-- y se pueden marcar varias regiones seguidas. Un clic sin pareja se
rechaza con un mensaje real ("... quedó sin pareja") en vez de
adivinar qué hacer con él.

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/spectroscopy/test_extended_extraction.py` (nuevo, 7 tests) | recupera el flujo total real de una región plana; rechaza ventanas de cielo que solapan una región ancha; documenta que `sky_windows=()` invalida la columna en vez de inventar cero; resuelve dos bins independientes de una misma nebulosa; reporta fallos (región fuera de imagen) sin detener el lote; valida forma de entrada |
| `tests/gui_smoke/test_qt_app_picking_smoke.py` (+2 tests, sobre el archivo existente de pruebas de picking) | extracción de una región vía dos clics manuales, de principio a fin (incluye el hilo de fondo real); rechaza un clic sin pareja con mensaje real en el log |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (emisión "extendida" sintética de nivel plano conocido inyectada sobre filas reales del frame, lejos de la traza puntual de la propia Vega) | error relativo tras extracción: **0.00%** (recuperación exacta del flujo extra inyectado); multi-región (2 bins) sin fallos |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **961 passed** (antes del slice: 954 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **176 passed** (antes: 174) |

## 4. Qué queda fuera de este slice

Del encargo original de 79 secciones: soporte échelle (§52-54), y el
bloque extendido de QC/informe/reproducibilidad (§63-78).
