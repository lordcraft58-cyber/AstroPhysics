# Informe 77 — Espectroscopía slice 22: tooltip real del visor 1D (§29)

Continuación de los informes 55-76. El usuario pidió cerrar todo lo que
quede de espectroscopía del encargo de 43 secciones; este es el primero
de la nueva ronda de slices.

## El hueco real

`SpectrumView.value_hovered` solo emitía `(x, y)` continuos
interpolados bajo el cursor, mostrados como "X: … Y: …" genéricos en la
barra de estado -- nunca el pixel/λ real más cercano, su error real, ni
la S/N derivada, aunque varios procesos (`spectroscopy.trace`, `spectroscopy.
multiaperture`, `spectroscopy.line`, `spectroscopy.line_profile_fit`,
`spectroscopy.identify_lines`...) ya calculaban una incertidumbre real
por punto (`_uncertainty_adu`) que nunca llegaba a la serie graficada.

## Cambios

- `SpectrumSeries` (`spectrum_plot_data.py`): nuevo campo `y_error: np.ndarray | None = None`, puramente aditivo.
- `registry.py`: las 7 construcciones de la serie "Flujo"/"Flujo extraído" ya existentes (`_run_spectral_trace`, `_run_multi_aperture`, `_run_extended_extraction`, `_run_continuum_fit_central_row`, `_run_line_measurement_central_row`, `_run_line_profile_fit_central_row`, `_run_identify_object_lines`) ahora pasan `y_error` real -- ya calculado en cada una para su propio resumen de S/N, nunca una magnitud nueva. Dos de ellas (`_run_continuum_fit_central_row`, `_run_identify_object_lines`) no llamaban a `_uncertainty_adu` todavía; se añadió la misma llamada ya usada en el resto.
- `SpectrumView`: nuevo método `_nearest_real_point(x_query)` -- el punto REAL más cercano (nunca interpolado) de la primera serie con datos finitos, con su `y_error` real si la serie la lleva. Nueva señal `point_hovered(x, y, y_error, x_label, y_label)`, emitida junto a la ya existente `value_hovered` (sin tocarla).
- `main_window.py`: `_on_spectrum_point_hovered` (reemplaza `_on_spectrum_value_hovered`) construye el texto real: `"{x_label}: {x}  {y_label}: {y}  Error: {error o N/D}  S/N: {y/error o N/D}"` -- usa el `x_label` real que cada proceso ya pone ("Píxel (dispersión)" o "Longitud de onda (Å)"), nunca inventa cuál es.

## Validación

- `ruff check`: limpio.
- `tests/gui_smoke/test_qt_app_spectrum_view_smoke.py` (+3 tests): snapshot al punto real más cercano con error/S-N reales; `NaN` honesto sin incertidumbre real; todo `NaN` fuera del área de la gráfica.
- Suite unitaria completa: **1019 passed** (sin cambio -- solo hilo de un valor ya calculado, sin lógica nueva a nivel de registro).
- Suite de humo GUI completa: **187 passed** (antes: 184).
- Validación real sobre `Vega_1sec_1x1__frame6.fit` (vía `spectroscopy.trace`, mismo clic real ya usado en slices anteriores): la serie extraída lleva `y_error` real con la misma forma que el flujo, todo positivo donde es finito.

## Qué queda fuera

El selector de unidades (nm/μm, §15) sigue pendiente -- próximo slice.
