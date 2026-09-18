# 49 — Construcción: visor de espectros 1D real

A petición explícita del usuario ("ponte con el visor de espectros"),
tras el resumen de pendientes del informe 48: reemplazar la "tira 1D
repetida como imagen 2D" que usaban `spectroscopy.continuum`/`trace`/
`line`/`multiaperture` desde la Fase 9.5 -- limitación documentada
explícitamente en cada uno de esos cuatro cierres -- por un widget Qt
dedicado con ejes reales, zoom/pan e interacción de verdad.

## Qué se construyó

**Contrato de datos puro** (`qt_app/spectroscopy/spectrum_plot_data.py`,
deliberadamente SIN ningún import de PySide6): `SpectrumSeries` (x, y,
color, estilo), `SpectrumMarker` (banda vertical resaltada, p. ej. una
ventana de medición) y `SpectrumPlotData` (varias series + marcadores +
etiquetas de ejes). Esta separación no es incidental: `qt_app/processes/
registry.py` documenta explícitamente en su propio docstring que debe
seguir siendo "numpy puro, comprobable sin Qt" (`tests/unit/qt_app/
test_registry.py` se ejecuta en un venv sin PySide6 instalado,
verificado en vivo antes de tocar nada) -- si el contrato de datos
viviera en el mismo módulo que el widget, importar `SpectrumPlotData`
desde `registry.py` habría arrastrado PySide6 a un módulo que hoy no lo
necesita para nada. `series_color(index)` (paleta real del tema,
`qt_app.theme.DARK`, también sin Qt) vive en el mismo módulo puro.

**Widget real** (`qt_app/spectroscopy/spectrum_view.py`, `SpectrumView`,
`QWidget` + `QPainter` directo -- sin `QGraphicsView`/escena, mismo
criterio que ya usa `ImageView` para su propia interacción, pero un
trazo de línea no necesita manipular ítems, solo redibujarse):

- Ejes con gridlines, marcas y etiquetas reales (5 divisiones,
  formateo adaptativo según el rango) y título de eje X/Y.
- Hasta varias series superpuestas (trazo continuo, discontinuo para un
  ajuste superpuesto, o puntos sueltos), con leyenda real cuando hay más
  de una -- ancho medido por fuente real, nunca un ancho fijo que
  recorte una etiqueta larga (bug real encontrado y corregido durante
  la validación visual, ver más abajo).
- Marcadores de banda vertical (p. ej. la ventana real usada para medir
  una línea), con su etiqueta centrada sobre el ancho real del texto,
  no sobre el ancho de la propia banda (mismo bug de recorte).
- **Zoom a rueda de ratón** centrado en el cursor (mismos factores
  1.25/0.8 que ya usa `ImageView`), **arrastre con clic izquierdo** para
  desplazar la vista, **doble clic** para restablecer al rango completo
  de los datos.
- **Lectura en vivo bajo el cursor** (`value_hovered(x, y)`), cableada a
  la misma barra de estado que ya usa el "readout" de píxel de
  `ImageView` -- mismo lenguaje de interacción en todo el taller.
- Respeta huecos reales (`NaN`) en los datos como huecos reales en el
  trazo -- nunca los rellena para poder dibujar algo (relevante para el
  espectro combinado del motor 85, que sí puede tener `NaN` honesto).

## Cableado

- `main_window.py`: `add_spectrum_window(plot_data, title)` (mismo
  patrón que `add_image_window`), `_on_spectrum_value_hovered` cableado
  a `readout_label`.
- `_on_process_finished`: si `result.artifacts["spectrum"]` está
  presente, abre un `SpectrumView`; si no, cae al camino antiguo de
  `output_data`/`add_image_window` -- ningún otro proceso del taller
  cambia de comportamiento.
- Los cuatro procesos de espectroscopía (`registry.py`) ya construyen un
  `SpectrumPlotData` real en vez de la tira de imagen: `continuum`
  (flujo + continuo ajustado, discontinuo), `trace` (flujo extraído),
  `line` (flujo + continuo + la ventana de medición real marcada), y
  `multiaperture` (una serie por apertura, coloreada por
  `series_color`). Ninguno cambia su matemática -- es una capa de
  presentación pura sobre los mismos arrays que ya producían.
- El diálogo "Combinar espectros..." (motor 85) también se migró: su
  salida ya no rellena los `NaN` de puntos sin cobertura con la mediana
  solo para poder dibujar una imagen -- el visor real los muestra como
  huecos reales en el trazo.

## Bug real encontrado y corregido durante la validación visual

La primera versión recortaba el texto de la leyenda y de la etiqueta
del marcador al ancho de su propio contenedor geométrico (el ancho de
la banda marcada, o una caja fija de 80px para la leyenda) --
`QPainter.drawText(QRectF, flags, texto)` recorta al rectángulo dado por
defecto. Con una banda de medición más estrecha que su propia etiqueta
("Ventana de medición") o una etiqueta de leyenda más larga que 80px
("Continuo ajustado"), el texto salía visiblemente cortado
("ana de med" en vez de "Ventana de medición"). Se detectó ejecutando
la app real bajo Xvfb y comparando una captura de pantalla real (no
solo que las pruebas automatizadas pasaran) -- exactamente el tipo de
defecto que un test de "no lanza excepción" nunca habría encontrado.
Corregido midiendo el ancho real del texto con `QFontMetrics` antes de
construir el rectángulo de dibujo, en vez de asumir un ancho fijo.

## Tests

- `tests/gui_smoke/test_qt_app_spectrum_view_smoke.py` (10 tests,
  nuevo): mapeo dato↔píxel real (ida y vuelta), restablecer vista tras
  modificarla a mano, zoom de acercar/alejar real (el rango se estrecha/
  ensancha), arrastre real que desplaza el rango, doble clic que
  restablece tras un zoom real, lectura bajo el cursor con coordenadas
  de dato reales dentro del área de la gráfica y `NaN` real fuera de
  ella, una serie con un hueco `NaN` que no lanza excepción al
  dibujarse, un marcador + leyenda que tampoco lanzan excepción.
- `tests/unit/qt_app/test_registry.py`: la prueba de `spectroscopy.trace`
  se reescribió (ya no existe la tira de imagen que comprobaba) para
  verificar el `SpectrumPlotData` real; `spectroscopy.continuum` ganó
  aserciones sobre sus dos series (`Flujo`/`Continuo ajustado`,
  discontinua); dos pruebas nuevas para `spectroscopy.line` (marcador de
  ventana real, dentro de sus límites) y `spectroscopy.multiaperture`
  (una serie real por apertura, con colores distintos). Estas pruebas
  siguen siendo 100% numpy -- nunca importan Qt, confirmando que la
  separación de contrato se sostiene de verdad, no solo de palabra.
- `tests/gui_smoke/test_qt_app_picking_smoke.py` /
  `test_qt_app_spectroscopy_combine_smoke.py`: las pruebas existentes de
  `trace`/`line`/`multiaperture`/combinar ganaron aserciones
  `isinstance(..., SpectrumView)` reales sobre la ventana resultante, en
  vez de asumir el tipo antiguo (`combine`'s test accedía a
  `combined_view.data`, que ya no existe -- actualizado para leer
  `combined_view._data.series[0].y`).
- **Validación visual real** (no solo tests automatizados): captura de
  pantalla de la app completa bajo Xvfb ejecutando `spectroscopy.line`
  (ejes, leyenda con dos series, banda de ventana marcada, texto legible
  de extremo a extremo) y `spectroscopy.multiaperture` (dos series
  coloreadas distintas con su propia leyenda) -- así se encontró el bug
  de recorte de texto, que ningún test automatizado detectó.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **695 passed, 21 skipped, 1 xfailed** (antes: 693) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **133 passed** (antes: 123) |

## Incidente durante el desarrollo (sin relación con el motor)

Al comprobar el lint con `ruff` en el venv `aps-gui`, se detectó que
tenía una versión de `ruff` distinta (0.16.7) a la fijada del proyecto
(0.15.8 en `aps-test`), lo que ya se sabía por el cierre 46/47. Al
intentar diagnosticarlo se ejecutó por error `pip install ruff` (sin
version pin) DENTRO del venv `aps-test` -- lo actualizó a 0.16.8 y
rompió el gate de lint real del proyecto (145 errores nuevos sobre
código ya cerrado y probado). Detectado de inmediato al re-ejecutar
`ruff check` sobre código ya validado; corregido reinstalando
`ruff==0.15.8` en ese mismo venv antes de continuar. Ningún archivo del
proyecto se vio afectado -- fue un error de entorno de desarrollo, no de
código, pero se documenta por la misma disciplina de honestidad que
rige el resto del proyecto.

## Deliberadamente NO tocado en esta pasada

- **Selección/lectura de un punto exacto con clic** (p. ej. para leer un
  valor concreto sin depender del hover). El "readout" en vivo ya cubre
  ese caso de uso sin necesitar una interacción nueva.
- **Exportar la gráfica como imagen.** El taller ya tiene "Exportar
  última tabla a CSV..." para los datos subyacentes; exportar el propio
  dibujo (PNG/SVG) es una capacidad nueva y separada, no pedida.
- **Colisión de la leyenda con los datos** cuando una serie plana cae
  justo bajo la esquina superior derecha (visible en la captura de
  multi-apertura, sin llegar a solaparse en ese caso concreto). Una
  leyenda que evite la colisión con los datos reales sería una mejora
  cosmética legítima, pero no un defecto funcional -- ningún dato se
  pierde ni se malinterpreta.

## Cambio de motor

Motor #87 cerrado. Los cuatro procesos de espectroscopía del taller (y
el diálogo de combinación) ya muestran un espectro real, no un
workaround. Disponible para el siguiente motor según criterio propio de
prioridad: artefactos DONUT/GRADIENT, `spectroscopy.fluxcal` (bloqueado
por datos), desmezclado de aperturas solapadas, o el tipo `Spectrum`
unificado (refactor de arquitectura, deliberadamente diferido varias
veces).
