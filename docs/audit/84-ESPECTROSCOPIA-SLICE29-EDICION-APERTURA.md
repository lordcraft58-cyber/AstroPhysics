# Informe 84 — Espectroscopía slice 29: edición interactiva de la apertura (§2)

Continuación del informe 83. Cierra el último hueco real y grande que
quedaba del informe 71: hasta ahora, el overlay de traza/apertura/cielo
(slice 17) era solo de LECTURA -- ver el overlay no permitía ajustarlo.
Este slice lo hace editable a golpe de ratón, recalculando con la MISMA
traza ya conocida, sin retrazar ni pedir un nuevo clic.

## Alcance real (deliberado)

- **Editar**: arrastrar cualquiera de los dos bordes de la apertura
  (línea discontinua, arriba o abajo de la traza) cambia el semiancho
  real en vivo -- el overlay se redibuja durante el arrastre.
- **Recalcular**: al soltar el ratón, `recalculate_extraction` reextrae
  con el mismo `TraceResult` ya calculado (nunca se retraza) y el nuevo
  semiancho -- abre una ventana de espectro nueva con el resultado real,
  igual que cualquier extracción, y deja una entrada real en el
  historial de procesamiento de la vista (§36, slice 27).
- **Bloquear**: menú Vista → "Bloquear/desbloquear edición de apertura
  en la imagen activa (§2)" -- mientras está bloqueada, un clic sobre el
  borde de la apertura no entra en modo arrastre (protección real contra
  un arrastre accidental).
- **Fuera de alcance, documentado**: edición de las regiones de cielo
  (solo la apertura es arrastrable en este slice -- cada `SkyWindow`
  tiene dos grados de libertad independientes, offset y semiancho, que
  necesitarían su propia geometría de arrastre); y edición de varias
  aperturas a la vez (`spectroscopy.multiaperture`/`extended_extraction`
  producen VARIOS overlays simultáneos -- `ImageView._trace_overlay_
  single` solo se activa con exactamente UNO, así que esos procesos
  siguen siendo de solo lectura). "Añadir/quitar" una apertura completa
  no se construyó como acción separada: ya existe -- volver a ejecutar
  'Extracción de traza' con un clic distinto ya reemplaza la apertura
  completa, sin necesitar un botón nuevo.

## Diseño

- `qt_app/spectroscopy/trace_overlay_data.py`: nuevo `TraceEditContext`
  (traza real, datos, incertidumbre, máscara, extractor y parámetros de
  cielo YA usados) + `recalculate_extraction(context, new_aperture_
  half_width)` -- reutiliza literalmente `context.extractor` (el mismo
  `extract_sum`/`extract_mean`/`extract_optimal` que ya se usó), nunca
  duplica la física de extracción ni recalcula el cielo o la traza desde
  cero.
- `qt_app/processes/registry.py`: `_run_spectral_trace` y
  `_run_autoprocess_spectrum` (las dos únicas que producen UNA traza)
  añaden `artifacts["trace_edit_context"]` con el contexto real recién
  calculado.
- `qt_app/mdi/image_window.py` (`ImageView`): `set_trace_overlay` guarda
  el overlay real (`_trace_overlay_single`, solo si es uno único).
  `mousePressEvent` prueba si el clic cae dentro de una tolerancia real
  (3 px de datos) del borde de apertura en la columna más cercana; si
  sí, entra en modo arrastre (nunca si `trace_overlay_locked` o si hay
  una sesión de picking activa). `mouseMoveEvent` redibuja el overlay en
  vivo con el semiancho real bajo el cursor (nunca menor a 0.5 px).
  `mouseReleaseEvent` (nuevo, no existía) confirma el cambio y emite
  `aperture_edited(nuevo_semiancho)`.
- `qt_app/main_window.py`: `_on_aperture_edited` llama a `recalculate_
  extraction` con el `trace_edit_context` real de la vista, abre la
  ventana de espectro recalculada, y registra la entrada real en
  `view.processing_history`. `_toggle_active_trace_overlay_lock` (menú
  Vista) alterna `view.trace_overlay_locked` en la imagen activa.

## Validación

- `ruff check`: limpio en los cinco archivos tocados/nuevos.
- `tests/unit/qt_app/test_trace_overlay_data.py` (nuevo, 3 tests):
  `recalculate_extraction` reutiliza la misma traza con un semiancho
  distinto (más apertura -> más señal capturada, mismo perfil positivo);
  resultado idéntico a llamar al extractor original directamente con
  los mismos argumentos; rechazo honesto de un semiancho no positivo.
- `tests/unit/qt_app/test_registry.py` (+2 tests): `spectroscopy.trace`
  y `spectroscopy.autoprocess` reportan un `trace_edit_context` real
  utilizable con `recalculate_extraction`.
- `tests/gui_smoke/test_qt_app_aperture_edit_smoke.py` (nuevo, 3 tests):
  arrastre real de extremo a extremo (clic en el borde real, movimiento
  a una nueva posición, soltar) recalcula la extracción real y abre
  exactamente una ventana nueva, con la entrada real en el historial;
  bloquear la vista impide entrar en modo arrastre; un clic lejos de
  cualquier borde real (en el centro de la traza) tampoco lo activa.
- Suite unitaria completa: **1067 passed** (antes: 1063).
- Suite de humo GUI completa: **196 passed** (antes: 193).
- Validación real sobre `Vega_1sec_1x1__frame6.fit`: traza real vía el
  registro de procesos, `trace_edit_context` real capturado, y
  `recalculate_extraction` con el doble y la mitad del semiancho
  original -- mediana de flujo real mayor con más apertura y menor con
  menos, monótono como corresponde a una fuente real con perfil
  positivo, reutilizando la MISMA traza (y=602.0) sin volver a trazar.

## Cierre del informe 71

Con este slice se cierran todos los huecos reales grandes identificados
en el informe 71 (§2, §3, §5, §13, §15, §25, §28, §29, §31, §32, §34,
§35, §36, §37, §39, §42, más los ya cerrados en slices anteriores).
Quedan solo verificaciones/auditorías menores de baja prioridad
(§1/§7/§11/§14/§18) y §26 (clasificador de tipo espectral, de baja
viabilidad real sin una biblioteca de plantillas verificada -- mismo
límite ya documentado para §25 en el informe 83).
