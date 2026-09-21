# Informe 75 — Espectroscopía slice 20: informe de QC unificado (§31)

Continuación de los informes 55-74. Cuarto slice construido directamente
a partir de la auditoría del informe 71: cierra §31 -- hasta ahora, cada
diagnóstico real de calidad (RMS de traza, RMS de calibración en
longitud de onda, S/N, píxeles marcados) vivía disperso en el resumen de
un proceso distinto, sin ningún sitio que los reuniera con un veredicto
único.

## 1. El hueco real

`spectroscopy.trace` ya reportaba `trace.rms_residual_px` y una S/N
mediana en su resumen; `spectroscopy.quality_map` ya reportaba píxeles
marcados; `view.fitted_wavelength_solution.rms_residual` ya existía en
cuanto se ajustaba una calibración -- pero un usuario tenía que correr
tres procesos distintos y leer tres resúmenes distintos para hacerse una
idea de si una reducción es de fiar, sin ningún veredicto agregado ni
umbral explícito de qué cuenta como "bueno".

## 2. `astrophysics_suite/spectroscopy/qc_report.py` (nuevo, sin Qt)

`QCStatus` (OK/WARNING/ERROR/N-D), `QCMetric` (nombre, estado, texto del
valor, guía del umbral usado) y `QCReport` (tupla de métricas +
`overall_status`, el peor estado real entre las disponibles -- N/D solo
si NINGUNA métrica pudo calcularse, nunca por defecto).

Cuatro funciones constructoras, cada una tomando SOLO números que otro
motor ya calculó -- **este módulo nunca calcula una magnitud nueva**,
solo clasifica:

- `trace_quality_metric(rms_px, n_columns_used, n_columns_total)` --
  desde `trace.TraceResult.rms_residual_px`/`n_columns_used_for_fit`
  reales; se rebaja a WARNING si menos de la mitad de las columnas tuvo
  evidencia real, aunque el RMS numérico sea bajo (`n_columns_used_for_fit`
  ya avisaba de esto en su propio docstring desde antes de este slice --
  ahora ese aviso se traduce en un estado real, no solo en un comentario).
- `wavelength_calibration_quality_metric(rms_residual_angstrom | None)`
  -- desde `wavelength.WavelengthSolution.rms_residual` real, o `N/D`
  honesto si la imagen no tiene una calibración ajustada todavía.
- `snr_metric(median_snr)` -- desde la misma fórmula flujo/incertidumbre
  ya usada en `_run_spectral_trace` (no una nueva).
- `pixel_quality_metric(n_bad, n_total, saturate_available)` -- desde el
  mismo `frame2d.build_pixel_mask`/`imtools.cosmic_rays.detect_cosmic_rays`
  que ya usa `spectroscopy.quality_map`, aplicado a TODO el fotograma.

Los umbrales OK/WARNING/ERROR (p. ej. RMS<0.5 px bueno, S/N>=20 buena)
son guías orientativas de espectroscopía de aficionado/telescopio
pequeño, explícitamente declaradas como tales en `QCMetric.guideline`
-- nunca presentadas como un estándar absoluto.

## 3. `spectroscopy.qc_report` (nuevo proceso, `registry.py`)

Reutiliza EXACTAMENTE la misma traza/extracción real que "Extracción de
traza" (mismo clic obligatorio marcando el centro espacial inicial --
nunca un centro geométrico asumido: un frame real de Vega ya demostró en
slices anteriores que la traza real puede estar a más de 80 px del
centro geométrico del sensor, así que adivinarlo sería tan poco fiable
como el propio bug que motivó §31) y la misma máscara de calidad de
fotograma completo que "Mapa de calidad de píxeles" -- sin recalcular
ninguna física nueva, solo ensamblando `QCReport` a partir de esos
números reales más `view.fitted_wavelength_solution` si existe.

Devuelve `summary` con el veredicto global + un resumen de una línea por
métrica, `log_lines` con el detalle y la guía de cada una, y una `Table`
exportable a CSV -- sin `output_data` ni ventana nueva: es un informe de
lectura, no una imagen ni un espectro.

## 4. Validación

| Verificación | Resultado |
|---|---|
| `ruff check` (código nuevo/modificado) | limpio |
| `tests/unit/spectroscopy/test_qc_report.py` (nuevo, 11 tests) | umbrales de las 4 métricas, degradación honesta con baja cobertura de columnas, `N/D` real sin calibración/sin incertidumbre, `overall_status` = peor estado real (N/D nunca cuenta como fallo, N/D total si nada se pudo calcular), guías siempre declaradas como orientativas |
| `tests/unit/qt_app/test_registry.py` (+3 tests) | exige exactamente un clic; reporta las 4 métricas con `N/D` real sin calibración; con una solución de longitud de onda real inyectada, la métrica correspondiente deja de ser `N/D` |
| `tests/gui_smoke/test_qt_app_qc_report_smoke.py` (nuevo, 1 test) | flujo completo por clic real; confirma que NO abre ninguna ventana nueva (es un informe, no una imagen/espectro) |
| Suite unitaria completa (`pytest tests/ --ignore=tests/gui_smoke`) | **1011 passed** (antes del slice: 997 passed) |
| Suite de humo GUI completa (`xvfb-run pytest tests/gui_smoke/`, venv `aps-gui`) | **183 passed** (antes: 182) |
| Motor de extremo a extremo sobre `Vega_1sec_1x1__frame6.fit` real (vía `qt_app.processes.registry`, mismo clic real y=602.0 ya usado y validado en slices anteriores) | traza real: RMS=0.078 px (1072/1391 columnas con evidencia real) -> OK; S/N mediana real=294.5 -> OK (fuente puntual brillante real); calidad de píxeles sin GAIN/rayos cósmicos: 0/1445249 -> OK; calibración en longitud de onda: N/D real (sin lámpara ajustada); con GAIN/RDNOISE inyectados + detección de rayos cósmicos activada: 29352/1445249 (2.031%) -> ERROR real, veredicto que sí cambia con datos reales distintos |

## 5. Qué queda fuera de este slice

Del informe 71, siguen pendientes: edición manual interactiva del
overlay 2D (§2/§3/§5/§35), calibración por estrella de referencia (§13),
botón "AUTOPROCESS SPECTRUM" (§34, que podría reutilizar este informe de
QC como paso final del pipeline automático), y el resto de huecos reales
listados en ese informe. El informe de QC de este slice NO incluye
todavía la fracción de columnas saturadas dentro de la ventana de
apertura específica (solo el recuento sobre TODO el fotograma, igual que
"Mapa de calidad de píxeles") ni un historial de informes anteriores de
la misma imagen -- ambos, fuera del alcance mínimo de §31.
