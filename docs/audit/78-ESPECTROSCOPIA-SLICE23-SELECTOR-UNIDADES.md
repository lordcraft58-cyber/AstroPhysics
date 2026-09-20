# Informe 78 — Espectroscopía slice 23: selector de unidades Å/nm/μm (§15)

Continuación del informe 77. La parte de §15 que ya estaba resuelta
(nunca mostrar "Píxel" cuando hay una calibración real -- cada proceso
ya cambia `x_label` a "Longitud de onda (Å)" solo cuando de verdad hay
una calibración) se deja tal cual; este slice añade la pieza que
faltaba: un selector real Å/nm/μm que convierte el eje en caliente.

## Cambios

- `spectrum_plot_data.py`: nuevo campo `SpectrumPlotData.x_unit` (`"Å"`
  cuando el eje es una longitud de onda real; `""` en cualquier otro
  caso -- nunca se ofrece un selector donde no hay unidad física real).
  Nueva función pura `convert_wavelength_plot_data(plot_data, to_unit)`
  -- conversión de unidades real (1 Å = 0.1 nm = 1e-4 μm), nunca toca
  `y`/`y_error` (son flujo/incertidumbre, no longitud de onda). **Bug
  real encontrado y corregido por su propio test unitario antes de
  llegar a la GUI**: el factor de escala estaba invertido (Å->nm
  multiplicaba por 10 en vez de dividir) -- atrapado por
  `test_convert_angstrom_to_nm_divides_by_ten` en el primer intento.
- Tres sitios que ya construían un eje real en Å (`_run_identify_object_lines`, `telluric_correction_dialog.py`, `flexure_correction_dialog.py`) ahora declaran `x_unit="Å"`.
- `SpectrumView`: combo `unit_combo` (Å/nm/μm) SOLO cuando `plot_data.x_unit` es real -- construido como widget hijo flotante posicionado a mano (`_position_unit_combo`/`resizeEvent`), NUNCA envolviendo `SpectrumView` en un contenedor nuevo: envolver habría roto `sub_window.widget()` como `SpectrumView` en decenas de tests de humo ya existentes de toda la sesión (identify_lines, telluric, flexure...) que asumen ese tipo exacto. `set_plot_data` (ya existente desde el slice 22) hace el cambio real de unidad.

## Validación

- `ruff check`: limpio.
- `tests/unit/qt_app/test_spectrum_plot_data.py` (nuevo, 6 tests, sin PySide6): conversión Å->nm/μm real, ida y vuelta es la identidad, mismo-a-mismo es no-op, rechaza un eje sin unidad real y una unidad desconocida.
- `tests/gui_smoke/test_qt_app_spectrum_view_smoke.py` (+2 tests): sin combo para un eje de píxel; combo real que convierte el eje en caliente.
- Suite unitaria completa: **1025 passed** (antes: 1019).
- Suite de humo GUI completa: **189 passed** (antes: 187) -- sin regresión en identify_lines/telluric/flexure, confirmando que la compatibilidad con `sub_window.widget()` se conservó.
- Validación real sobre `Vega_1sec_1x1__frame6.fit` (vía `spectroscopy.identify_lines`): `x_unit` real = `"Å"`; conversión real a nm coincide exactamente con dividir por 10 el eje real ya calibrado.

## Qué queda fuera

`wavelength_fit_dialog.py` (tabla interactiva de arco) sigue sin selector -- mismo motivo ya documentado en el informe 74 para la columna de vacío: modificar ese flujo de edición activo queda fuera del alcance mínimo. Siguiente: §3 (modo de extracción "media") y §19 (continuo con spline + regiones manuales).
