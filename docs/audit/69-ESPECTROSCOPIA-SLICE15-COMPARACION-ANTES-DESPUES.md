# Informe 69 — Espectroscopía slice 15: comparación visual antes/después

Continuación de los informes 55-68. Segundo motor del bloque §63-78
("comparación antes/después") sobre los dos diálogos de corrección más
directamente comparables de esta serie: flexión (slice 9, §44) y
telúrica (slice 10, §46).

## 1. El hueco real

Ambos diálogos ya aplicaban su corrección real y reportaban el efecto en
TEXTO (Δpíxel/Δλ/Δv en flexión; N píxeles corregidos en telúrica) o en
una tabla, pero nunca en un GRÁFICO -- el usuario tenía que confiar en
los números o abrir manualmente dos ventanas de espectro por separado
para comparar visualmente.

## 2. Botón "Ver comparación antes/después..." (ambos diálogos)

Reutiliza `SpectrumPlotData`/`SpectrumSeries`/`series_color` (ya
existentes, del visor de espectros 1D) y `MainWindow.add_spectrum_window`
(ya existente) -- ninguna infraestructura de gráfico nueva, solo una
llamada más a lo ya construido.

- **`FlexureCorrectionDialog`**: overlay de tres series -- la referencia
  real, la nueva exposición SIN corregir (misma solución de longitud de
  onda que la referencia, mostrando la deriva real tal cual estaba) y la
  nueva exposición corregida (con `shifted_solution`) -- deja ver
  directamente si la corrección alinea de verdad las líneas con la
  referencia.
- **`TelluricCorrectionDialog`**: overlay de dos series -- el espectro
  científico crudo y el corregido, en la misma longitud de onda -- deja
  ver directamente que la banda telúrica se redujo/eliminó, y que el
  resto del espectro no cambió (coherente con la disciplina de la propia
  slice 10 de no tocar nada fuera de banda).

## 3. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código modificado) | limpio |
| `tests/gui_smoke/test_qt_app_flexure_correction_smoke.py` (+aserciones en el test existente) | el botón abre una ventana nueva de espectro con 3 series reales |
| `tests/gui_smoke/test_qt_app_telluric_correction_smoke.py` (+aserciones en el test existente) | el botón abre una ventana nueva de espectro con 2 series reales |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **979 passed** (sin cambios -- ninguna prueba unitaria nueva, solo aserciones añadidas a pruebas de humo GUI ya existentes) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **178 passed** (sin cambios -- mismas funciones de prueba, con aserciones nuevas dentro) |

No se repite una validación con datos reales de Vega aparte: los motores
subyacentes (`flexure_correction.py`, `telluric_correction.py`) ya se
validaron con Vega real en las slices 9/10, y este slice no toca esa
física -- solo grafica los mismos resultados ya reales que esos motores
producen, con la misma cobertura de prueba de humo GUI de siempre.

## 4. Qué queda fuera de este slice

Del bloque §63-78: manejo de calibración por lotes, modo de vigilancia
de directorio, apilado espectral, versionado, base de datos de perfiles
de instrumento, modos vista-rápida vs. reducción científica, informe
PDF/HTML, motor de validación física, separación de API del pipeline,
exportación de configuración reproducible. Y, del resto del encargo de
79 secciones, soporte échelle (§52-54).
