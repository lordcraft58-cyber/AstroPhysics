# 48 — Construcción: motor de extracción multi-apertura

Tercer motor de la expansión de espectroscopía en esta racha (docs/audit/
13-... §7, 45/46/47-...), mismo criterio de prioridad: autocontenido y de
valor científico real directo. A diferencia de los dos anteriores (medir
una línea, combinar espectros), este no introduce matemática nueva --
**reutiliza** `trace_spectrum`/`extract_sum`/`extract_optimal` ya
probados, orquestándolos sobre varios objetos reales de la misma imagen
en vez de reimplementar el trazado o la extracción por una segunda vía
(mismo principio ya aplicado en el cierre 45 sobre `band_ratios`: separar
lo nuevo de lo ya probado, nunca duplicar un motor existente).

## Qué se construyó

`astrophysics_suite/spectroscopy/multiaperture.py`:

- `find_aperture_centers(data, *, min_snr=5.0, min_separation_px=10.0,
  max_apertures=20) -> list[float]` -- colapsa la imagen 2D a un perfil
  espacial 1D por **mediana** a lo largo de todo el eje de dispersión
  (robusta frente a una sola línea de emisión brillante o un rayo
  cósmico puntual, a diferencia de una simple suma), y detecta picos
  reales por encima de `min_snr` veces el ruido robusto (MAD) sobre el
  fondo. Si hay más candidatos que `max_apertures`, se queda con los más
  brillantes -- devueltos en orden espacial, no por brillo.
- `extract_multi_aperture(data, uncertainty, *, aperture_centers=None,
  ...) -> MultiApertureResult` -- traza y extrae una apertura real por
  cada centro (dado explícitamente, o detectado automáticamente si no
  se da ninguno), llamando a `trace_spectrum`/`extract_sum`/
  `extract_optimal` sin ningún cambio para cada una. **Nunca reimplementa
  el trazado ni la extracción.**
- **Resiliencia real por apertura**: una apertura que no se puede trazar
  (sin señal suficiente, centro fuera de la imagen) se reporta en
  `MultiApertureResult.failures` con el motivo real -- nunca detiene el
  lote completo ni se descarta en silencio. Las aperturas que sí se
  extraen conservan su propio `aperture_id` de origen (no se renumeran
  al descartar una fallida), para que el motivo de cada fallo siga
  siendo identificable.

## Cableado en la GUI

Nuevo proceso `spectroscopy.multiaperture` ("Extracción multi-apertura
(apall, varios objetos)") en `qt_app/processes/registry.py`,
`requires_picking=0` (marcas manuales ilimitadas, clic derecho para
terminar) -- misma convención que `spectroscopy.trace` para el eje
espacial (solo se usa la coordenada Y de cada clic). Con
"Detectar automáticamente" activo (por defecto), el mecanismo genérico
de auto-detección de `main_window.py` (ya usado por `photometry.aperture`/
`photometry.psf` con DAOStarFinder) gana una tercera rama específica que
llama a `find_aperture_centers` en vez de un detector de fuentes
puntuales 2D -- un objeto en una traza espectral es alargado a lo largo
de la dispersión, no compacto como una estrella, así que reutilizar el
detector de estrellas habría sido la misma "medición por una segunda vía
incorrecta" que el proyecto ya evita en otros motores. Cada apertura
extraída se muestra como su propia franja 1D (separadas por una fila en
negro), y la tabla resultante (`aperture_id`, centro, RMS de traza, flujo
mediano) queda exportable a CSV; los fallos de aperturas individuales
quedan en el registro del proceso, no ocultos.

## Tests

- `tests/unit/spectroscopy/test_multiaperture.py` (7 tests): detección
  de picos espaciales reales contra posiciones conocidas; detección
  vacía sobre un campo plano; selección de los más brillantes al
  limitar `max_apertures`; recuperación del flujo real inyectado por
  apertura (no solo "extrae algo"); detección automática end-to-end;
  **resiliencia real**: un centro fuera de imagen se reporta como fallo
  sin detener las otras dos aperturas válidas, que conservan su
  `aperture_id` original; validación de formas.
- `tests/integration/test_spectroscopy_multiaperture_pipeline.py` (1
  test): dos objetos reales distintos en la misma imagen 2D (misma
  rendija), cada uno con su propia línea de emisión real en una posición
  distinta -- detección automática de ambas aperturas, extracción,
  calibración en longitud de onda compartida y medición de línea (motor
  84) sobre cada espectro extraído por separado. Confirma no solo que
  cada apertura recupera su propia línea dentro de la tolerancia, sino
  que la línea del OTRO objeto NO aparece con fuerza comparable en la
  apertura equivocada -- prueba explícita de que las dos trazas no se
  mezclaron, el riesgo real de un motor multi-objeto.
- `tests/gui_smoke/test_qt_app_picking_smoke.py` (+2 tests): flujo
  completo por detección automática (sin picking) y por dos clics
  manuales, ambos verificando que las dos aperturas reales del campo
  sintético terminan en la tabla resultante.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **693 passed, 21 skipped, 1 xfailed** (antes: 685) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **123 passed** (antes: 121) |

## Deliberadamente NO tocado en esta pasada

- **Visor de espectros 1D dedicado.** Misma limitación ya documentada
  para el resto de `spectroscopy.*` desde la Fase 9.5.
- **Extracción simultánea con perfil espacial compartido entre
  aperturas** (como hace `extract_optimal` para una sola traza, pero
  fusionando la información de varias aperturas cercanas que se
  solapan). Cada apertura de este motor se extrae de forma
  **independiente** -- correcto para objetos bien separados (la prueba
  de integración usa 30 px de separación), pero no resuelve el caso de
  dos objetos con perfiles espaciales solapados, que necesitaría
  desmezclado real (como ya hace `photometry.psf` para PSFs 2D
  solapadas) -- capacidad nueva y más compleja, fuera de alcance aquí.
- **Tipo `Spectrum` unificado.** Sigue como PENDIENTE documentado en
  `docs/audit/13-...` §7.

## Cambio de motor

Motor #86 cerrado -- tercero consecutivo de la expansión de
espectroscopía (medición de líneas, combinación, multi-apertura).
Disponible para el siguiente motor según criterio propio de prioridad:
del backlog documentado en los informes 45-48 quedan abiertos los
artefactos DONUT/GRADIENT (mayor riesgo, toca `photometry/quality.py`),
`spectroscopy.fluxcal` (bloqueado por falta de catálogo de flujos
estándar externo), el tipo `Spectrum` unificado (refactor de
arquitectura, deliberadamente diferido varias veces) y el desmezclado de
aperturas solapadas mencionado arriba.
