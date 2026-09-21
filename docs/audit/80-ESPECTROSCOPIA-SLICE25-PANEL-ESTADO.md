# Informe 80 — Espectroscopía slice 25: panel de estado por objeto (§42)

Continuación del informe 79. Extiende el informe de QC unificado
(§31, slice 20) en vez de construir un panel nuevo por separado --
§42 pide exactamente la misma checklist ✓/✗ más rango λ + dispersión +
RMS, y todo eso ya vivía o casi vivía en `qc_report.py`.

## Cambios

- `qc_report.py`: dos métricas nuevas, `wavelength_range_metric` (rango
  real cubierto, en los dos extremos de la traza) y `dispersion_metric`
  (dispersión local real en el centro, vía `wavelength.local_dispersion_
  at_pixel` ya existente del slice 18) -- ambas `N/D` honesto sin
  calibración real, `OK` siempre que sí hay una (son informativas, no
  hay un rango/dispersión "malo" que penalizar).
- Deliberadamente NO se añade una fila de "resolución espectral global":
  R=λ/FWHM exige una línea real medida, y no hay una FWHM genérica del
  espectro completo que no sea inventada -- documentado explícitamente
  en el módulo para que quede claro que es una omisión intencional, no
  un olvido.
- `spectroscopy.qc_report` pasa de 4 a 6 filas; renombrado a "Informe de
  control de calidad / panel de estado" en el explorador de procesos.

## Validación

- `ruff check`: limpio.
- `tests/unit/spectroscopy/test_qc_report.py` (+6 tests): rango/dispersión `N/D` sin calibración; rango real en los dos extremos (orden creciente aunque la dispersión sea negativa); dispersión real recuperada de una solución lineal conocida.
- `tests/unit/qt_app/test_registry.py` (2 tests actualizados a 6 filas, con valores reales verificados para las dos filas nuevas).
- `tests/gui_smoke/test_qt_app_qc_report_smoke.py` (1 test actualizado).
- Suite unitaria completa: **1036 passed** (antes: 1031).
- Suite de humo GUI completa: **189 passed** (sin cambio en el total -- solo aserciones actualizadas en un test existente).
- Validación real sobre `Vega_1sec_1x1__frame6.fit`: las 6 filas reales, incluidas rango (5700.0-7646.0 Å) y dispersión (1.4000 Å/px) coincidiendo exactamente con la solución de referencia usada.

## Qué queda fuera

§34 (AUTOPROCESS SPECTRUM) es ahora el hueco real más grande que queda
del informe 71 -- siguiente slice.
