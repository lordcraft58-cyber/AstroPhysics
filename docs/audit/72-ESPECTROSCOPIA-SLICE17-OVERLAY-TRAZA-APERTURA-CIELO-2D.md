# Informe 72 — Espectroscopía slice 17: overlay de traza/apertura/cielo sobre la imagen 2D

Continuación de los informes 55-71. Primer slice construido directamente
a partir de la auditoría del informe 71 (encargo completo de 43
secciones): cierra el hallazgo más repetido y con más prioridad de esa
auditoría (§2, §3, §5, §28) -- el visor 2D nunca dibujaba la traza, los
límites de apertura ni las regiones de cielo sobre la imagen real.

## 1. El hueco real (confirmado por inspección directa antes de construir nada)

Hasta este slice, trazar y extraer un espectro era una caja negra desde
el punto de vista visual: un clic, y el resultado aparecía en una
ventana 1D nueva -- sin ver nunca, sobre la imagen 2D original, qué
traza se ajustó de verdad, qué límites de apertura se usaron, ni dónde
estaban las regiones de cielo. `ImageView` (`qt_app/mdi/image_window.py`)
ya tenía zoom/paneo/contraste (log/sqrt/lineal vía STF) real, pero cero
métodos de overlay.

## 2. `qt_app/spectroscopy/trace_overlay_data.py` (nuevo)

`TraceOverlay(trace_columns, trace_center_px, aperture_half_width,
sky_windows=(), label="")` -- contrato de datos puro, sin ningún import
de PySide6 (mismo motivo que `spectrum_plot_data.py`: `registry.py` debe
seguir siendo "numpy puro, comprobable sin Qt"). Reutiliza directamente
`trace.SkyWindow` (ya existente) en vez de reinventar una representación
propia de ventana de cielo.

## 3. `ImageView.set_trace_overlay`/`clear_trace_overlay` (nuevo)

Dibuja sobre la imagen real, como items de escena en coordenadas de
datos (persisten a través de cambios de STF/contraste, que solo tocan el
píxmap):

- La traza real (línea continua).
- Los límites REALES de apertura, `centro ± aperture_half_width` (línea
  discontinua, mismo color que la traza).
- Cada ventana REAL de cielo, `centro + offset ± semiancho` (línea
  discontinua azul).
- Varios objetos (multiapertura) se dibujan con colores distintos del
  ciclo de paleta del tema, para distinguirlos visualmente.

`set_trace_overlay` acepta un `TraceOverlay` único o una tupla (una
traza real por objeto).

## 4. Cableado en `registry.py`/`main_window.py`

Los tres procesos de trazado/extracción que ya calculaban una traza o
región real (`spectroscopy.trace`, `spectroscopy.multiaperture`,
`spectroscopy.extended_extraction`) ahora añaden
`artifacts["trace_overlay"]` a su `ProcessResult` con los datos REALES
ya calculados (nunca una aproximación nueva) -- `_on_process_finished`
en `main_window.py` los aplica a la ventana con
`view.set_trace_overlay(...)`, mismo mecanismo ya establecido que
`artifacts["spectrum"]`.

## 5. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/qt_app/test_registry.py` (+3 tests) | `spectroscopy.trace` reporta un `TraceOverlay` real con la traza/apertura/cielo correctos; `spectroscopy.multiaperture` reporta uno por apertura con la etiqueta correcta; `spectroscopy.extended_extraction` reporta un overlay de centro/semiancho constante coherente con la región marcada |
| `tests/gui_smoke/test_qt_app_trace_overlay_smoke.py` (nuevo, 3 tests) | `ImageView.set_trace_overlay`/`clear_trace_overlay` añaden y quitan EXACTAMENTE el número de items de escena esperado (traza + 2 límites de apertura + 2 líneas por ventana de cielo); acepta una tupla de overlays (multiapertura); `spectroscopy.trace` dibuja un overlay real de principio a fin vía clic real |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real | el overlay generado cubre las 1391 columnas reales del frame; el centro de traza real está siempre dentro de los límites reales de la imagen (0-1039); semiancho de apertura y ventanas de cielo reales coinciden exactamente con los parámetros usados |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **987 passed** (antes del slice: 984 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **182 passed** (antes: 179) |

## 6. Qué queda fuera de este slice

Deliberadamente MVP de solo lectura (visualización), no edición
interactiva -- de la propia auditoría (informe 71), quedan pendientes:
edición manual de traza/apertura/cielo arrastrando los límites dibujados
(§2/§3/§5/§35), informe de QC unificado (§31), resolución espectral
R=λ/FWHM (§32), conexión de `air_vacuum.py` (ya construido, sin usar
todavía) a un consumidor real (§24), calibración por estrella de
referencia (§13), botón "AUTOPROCESS SPECTRUM" (§34), y el resto de
huecos reales listados en el informe 71.
