# Informe 66 — Espectroscopía slice 12: detección de saturación cableada en trazado/extracción interactivos

Continuación de los informes 55-65. Cierra un hueco real encontrado al
auditar el resto del §63-78 (bloque de QC/diagnóstico) antes de
abordarlo: `astrophysics_suite/spectroscopy/frame2d.py`
(`build_pixel_mask`/`PixelFlag.SATURATED`) es un motor real y ya probado
desde antes de esta serie de slices (auditado con FITS reales de Vega/T
CrB, informe 55), pero **nunca tuvo ningún camino de uso interactivo**:
`spectroscopy.trace`, `spectroscopy.multiaperture` y el
`spectroscopy.extended_extraction` de la Slice 11 llamaban siempre a
`trace_spectrum`/`extract_sum`/`extract_optimal`/`extract_multi_aperture`/
`extract_multi_region` con `mask=None` implícito -- ningún píxel saturado
se excluía nunca de una traza o extracción hecha desde la GUI, por muy
saturado que estuviera.

## 1. `qt_app/processes/registry.py` -- `_saturation_mask_from_header`

Helper nuevo, reutilizado por los tres procesos de traza/extracción:

- Lee `params["_header"]["SATURATE"]` -- el mismo parámetro especial
  `_header` que `_start_process_worker` ya rellena automáticamente para
  todo proceso (poblado desde `view.header`, la cabecera FITS real).
- Si no hay un valor `SATURATE` real y positivo, la detección queda
  **inactiva**: `mask=None`, exactamente igual que la disciplina ya
  establecida en `detection.finder`/`frame2d.build_pixel_mask` -- nunca
  se inventa un umbral de saturación.
- Si lo hay, construye la máscara real con `build_pixel_mask(data,
  saturate_adu=...)` (motor existente, sin cambios) y cuenta cuántos
  píxeles de TODO el fotograma quedaron marcados `PixelFlag.SATURATED`.

Cableado en `_run_spectral_trace`, `_run_multi_aperture` y
`_run_extended_extraction`: la máscara se pasa a `trace_spectrum`/
`extract_sum`/`extract_optimal`/`extract_multi_aperture`/
`extract_multi_region` (todos ya aceptaban `mask`, ninguno necesitó
cambios) y el resumen del proceso reporta explícitamente cuántos píxeles
saturados se excluyeron y con qué umbral real -- nunca en silencio.

## 2. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código modificado) | limpio |
| `tests/unit/qt_app/test_registry.py` (+4 tests) | `_saturation_mask_from_header` inactivo sin `SATURATE` real (ausente, no numérico, o <= 0); detecta correctamente los píxeles reales por encima del umbral; `spectroscopy.trace` reporta la exclusión real en el resumen; sin `SATURATE` real, el resumen nunca menciona saturación |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | el frame real **no trae `SATURATE`** en su cabecera -- confirmado que la detección queda inactiva tal cual llega (comportamiento correcto, no un defecto de la prueba); con un `SATURATE=45000` inyectado (representativo de un CCD real de pozo lleno ~45000-55000 ADU, máximo real observado en el frame: 50632 ADU), se detectan exactamente 215 píxeles reales por encima del umbral y `spectroscopy.trace` los reporta en su resumen de principio a fin |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **965 passed** (antes del slice: 961 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **176 passed** (sin cambios -- wiring interno, ninguna prueba de GUI nueva) |

## 3. Qué queda fuera de este slice

Del bloque §63-78: conversión ADU↔electrón, manejo de calibración por
lotes, modo de vigilancia de directorio, apilado espectral, versionado,
base de datos de perfiles de instrumento, modos vista-rápida vs.
reducción científica, comparación antes/después, informe PDF/HTML, motor
de validación física, separación de API del pipeline, exportación de
configuración reproducible. Y, del resto del encargo de 79 secciones,
soporte échelle (§52-54).
