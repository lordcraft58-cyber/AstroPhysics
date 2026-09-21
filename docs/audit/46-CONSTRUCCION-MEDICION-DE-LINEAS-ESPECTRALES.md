# 46 — Construcción: motor de medición de líneas espectrales (EW/flujo/FWHM)

Siguiente motor tras el cierre de backlog del informe 45, elegido por
criterio propio de prioridad entre las brechas ahí documentadas
("Expansión completa de espectroscopía" -- extracción multi-apertura,
medición de líneas, combinación de espectros, tipo `Spectrum` unificado):
la medición de líneas es la más autocontenida y de menor riesgo -- no
toca ningún motor ya cerrado y probado, y cierra el hueco real que deja
hoy la cadena `trace -> wavelength -> continuum` (un espectro extraído,
calibrado y con su continuo ajustado, pero sin ninguna forma de medir
una línea sobre él).

## Qué se construyó

`astrophysics_suite/spectroscopy/lines.py` -- `measure_line(wavelength,
flux, continuum, *, expected_wavelength, window_halfwidth,
flux_uncertainty=None) -> LineMeasurement | None`, equivalente propio de
`splot`/`fitprofs` de IRAF:

- **Centroide** ponderado por `|flujo - continuo|` dentro de la ventana.
- **FWHM** por interpolación lineal entre los puntos reales que rodean
  cada cruce de media altura -- `None` (nunca extrapolado) si el perfil
  no cruza la media altura dentro de la ventana dada.
- **Ancho equivalente**, convención estándar de `splot` (positivo para
  absorción, negativo para emisión) -- `None` si el continuo no es
  estrictamente positivo en toda la ventana (dividir por continuo ≤0 no
  tiene sentido).
- **Flujo integrado** (`∫(flujo-continuo)dλ`), siempre calculable a
  diferencia del EW porque no depende de dividir por el continuo.
- **Propagación de error real** de `flux_uncertainty` a
  `integrated_flux_error`/`equivalent_width_error` vía pesos
  trapezoidales (`np.gradient` sobre la malla de longitud de onda).

Nunca busca una línea por su cuenta: `expected_wavelength`/
`window_halfwidth` los da el llamador -- mismo principio que ya rige
`measure_line`'s ventana gaussiana en otros motores del proyecto y evita
inventar qué se está midiendo. Sigue la convención de arrays sueltos
(`wavelength`, `flux`, `continuum`) que ya usan `trace.py`/
`wavelength.py`/`continuum.py`, sin introducir un tipo `Spectrum`
unificado -- esa unificación sigue documentada como pieza de
arquitectura mayor y separada (`docs/audit/13-...` §7, `45-...`).

## Cableado en la GUI

Nuevo proceso `spectroscopy.line` ("Medición de línea (splot)") en
`qt_app/processes/registry.py`, categoría "Espectroscopía", mismo patrón
que "Ajuste de continuo (fila central)": opera sobre la fila central de
la imagen activa tratada como espectro 1D (eje horizontal en píxeles sin
calibrar, mismo enfoque que el proceso de continuo ya existente),
requiere un clic (`requires_picking=1`) marcando el pico de la línea --
esa posición es literalmente `expected_wavelength`, así que el clic del
usuario cumple el mismo contrato de "nunca busca la línea sola" que ya
exige el motor. Ajusta el continuo internamente (mismo `fit_continuum`
que el proceso de continuo, con sus propios parámetros de grado/sigma),
propaga incertidumbre con el mismo modelo Poisson aproximado que ya usan
`photometry.aperture`/`spectroscopy.trace` (`sqrt(clip(data, 1, None))`),
y expone centro/FWHM/flujo integrado/EW con sus errores en resumen, log
y una tabla exportable a CSV (mismo mecanismo que el resto de procesos
con tabla).

## Tests

- `tests/unit/spectroscopy/test_lines.py` (10 tests): validación
  analítica contra una línea gaussiana sintética con parámetros
  conocidos -- `integrated_flux == amplitud·σ·√(2π)`,
  `FWHM == 2√(2ln2)·σ`, EW con el signo correcto para emisión/absorción,
  todo a `rel=1e-3` (no solo "no lanza excepción"). Más casos límite:
  ventana fuera de rango, menos de 3 puntos, FWHM inalcanzable dentro de
  la ventana, continuo no positivo, con/sin propagación de incertidumbre,
  formas incompatibles, `window_halfwidth` no positivo.
- `tests/integration/test_spectroscopy_line_measurement_pipeline.py` (1
  test): cadena completa real `trace_spectrum -> extract_sum ->
  fit_wavelength_solution -> fit_continuum -> measure_line` sobre una
  imagen 2D sintética con una línea de emisión gaussiana real inyectada
  -- no una llamada aislada a `measure_line` con arrays fabricados a
  mano, sino los motores reales encadenados tal como los usaría un flujo
  real.
- `tests/gui_smoke/test_qt_app_picking_smoke.py::
  test_line_measurement_process_runs_end_to_end_via_click` (1 test):
  flujo completo `main_window -> picking -> proceso real` con clic real
  y comprobación de que la tabla resultante recupera el centro real de
  la línea inyectada.

## Corrección durante el desarrollo

`np.trapz` fue eliminado en NumPy 2.4.6 (el proyecto exige
`numpy>=2.0`); primer uso de integración trapezoidal en todo
`astrophysics_suite/`, así que se detectó al ejecutar los tests por
primera vez, no por inspección previa. Corregido a `np.trapezoid` en
todo `lines.py` (confirmado por grep como el único uso en el proyecto,
sin necesidad de un shim de compatibilidad en ningún otro sitio).

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **674 passed, 21 skipped, 1 xfailed** (antes: 663) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **118 passed** (antes: 117) |

## Deliberadamente NO tocado en esta pasada

- **Visor de espectros 1D dedicado.** La medición se hace sobre la fila
  central mostrada como imagen 2D (misma limitación ya documentada para
  `spectroscopy.trace`/`spectroscopy.continuum` desde la Fase 9.5) -- un
  widget de gráfico 1D es una pieza de UI mayor y separada, no específica
  de este motor.
- **Lista de líneas conocidas por objeto/catálogo** (Hα, [OIII], etc.)
  para sugerir `expected_wavelength` automáticamente. El motor exige
  siempre una posición dada por el usuario (clic o valor conocido) por
  diseño -- añadir un catálogo de líneas es una capacidad nueva y
  separada, no parte de "medir una línea ya localizada".
- **Extracción multi-apertura, combinación/apilado de espectros, tipo
  `Spectrum` unificado.** Siguen como PENDIENTE documentado en
  `docs/audit/13-...` §7 y `45-...`, sin resolver aquí.

## Cambio de motor

Motor #84 cerrado. Disponible para el siguiente motor según criterio
propio de prioridad, sobre el mismo backlog documentado en el informe 45
(artefactos DONUT/GRADIENT, cableado de `spectroscopy.fluxcal` --
bloqueado por falta de catálogo de flujos estándar externo --, u otras
brechas de espectroscopía todavía abiertas).
