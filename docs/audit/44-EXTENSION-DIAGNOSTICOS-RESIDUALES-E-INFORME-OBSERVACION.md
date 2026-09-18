# 44 — Extensión: Diagnóstico de residuales + Informe de observación

Continuación directa del informe 43 (Scientific Visualization &
Reporting Engine v1). Aquel cierre dejaba explícitamente dos
limitaciones conocidas: (a) las secciones de astrometría/fotometría del
informe de candidato siempre decían "NO DISPONIBLE" porque el ajuste de
placa/punto cero es un resultado POR IMAGEN, no parte del `Candidate`;
(b) solo existía un informe por candidato, ningún agregado a nivel de
observación (el `reporting/observation.py` que sugería la arquitectura
original del encargo). Esta extensión cierra ambas.

## 1. `diagnostics/` -- diagnóstico genérico de residuales

`diagnostics/outliers.py::flag_outliers(values, *, sigma=3.0)`: marca
por índice qué valores de cualquier conjunto de residuales se apartan
más de `sigma` veces la desviación robusta (mediana + MAD, nunca media/
desviación estándar). Generaliza -- solo para DIAGNÓSTICO, no para
sustituir ningún rechazo real -- el mismo criterio que ya usan por
separado y sin compartir código `photometry.calibration.fit_zeropoint`,
`photometry.aperture`, `spectroscopy.continuum`/`trace` y
`astrometry.plate_solve._robust_fit_wcs` (confirmado por auditoría: los
5 usan mediana+MAD con el mismo `_MAD_TO_SIGMA = 1.4826`, duplicado en
cada archivo). **Deliberadamente no se tocó ninguno de esos 5
motores** -- refactorizarlos para que compartan este módulo es una
limpieza real pero separada, de mayor riesgo (tocaría 5 motores ya
probados) y fuera del alcance de "terminar el motor de informes".

`diagnostics/residuals.py::build_residual_diagnostic(residuals, *, unit, outlier_sigma=3.0)`:
envuelve un conjunto de residuales YA calculado por otro motor (nunca
recalcula el ajuste) en RMS/media/desviación máxima + los índices
atípicos de `flag_outliers`.

## 2. Nuevo tipo de gráfica: `DataSeries.kind="residual"`

Extensión mínima del contrato ya existente (mismo patrón que
`x_categories` para `kind="bar"` en el cierre 43): campo nuevo
`outlier_indices: tuple[int, ...] | None`, validado en `__post_init__`
(posiciones dentro de rango). `visualization/charts.py` dibuja línea
cero de referencia, puntos usados en azul, atípicos en rojo con
marcador "x" -- una representación real del ajuste, no decorativa: el
punto rojo es literalmente el mismo índice que `flag_outliers` marcó.

## 3. Astrometría/fotometría con residuales reales

`build_candidate_report` gana dos parámetros opcionales:
`wcs_solution: WCSSolution | None` y `zeropoint_fit: ZeropointFit | None`
-- ambos con `default=None`, así que ninguna llamada existente cambia
de comportamiento (verificado: los 594+ tests previos del motor de
informes siguen pasando sin modificar). Cuando se dan (y el ajuste que
traen tiene al menos un residuo real -- `wcs_solution_from_astropy`
sigue devolviendo `residuals_arcsec=()` porque no es un ajuste, solo una
lectura de cabecera, y ese caso se sigue tratando como NO DISPONIBLE):

- **Astrometría**: RMS del ajuste, nº de estrellas, nº de atípicos,
  tabla de residuales por estrella, gráfica `kind="residual"`.
- **Fotometría**: punto cero ± incertidumbre, RMS del ajuste, estrellas
  usadas/rechazadas POR EL PROPIO `fit_zeropoint` (su sigma-clip
  interno) + atípicos ADICIONALES marcados por este diagnóstico sobre
  lo que sobrevivió, tabla de residuales, gráfica `kind="residual"`.

**Brecha de arquitectura encontrada y documentada, no cerrada**: ni
`WCSSolution` ni `ZeropointFit` se persisten hoy en ningún sitio más
allá de la sesión de GUI activa (`ImageView.fitted_wcs_solution`,
`ProcessResult` transitorio) -- ninguno de los dos llega a
`Candidate`/`Observation`/`SessionState`. Por eso el botón "Generar
informe científico..." de la GUI **no** pasa estos parámetros todavía:
hacerlo requeriría decidir dónde persistirlos (¿en `Candidate`? ¿en
`ImageRef`? ¿solo mientras la ventana de imagen siga abierta?), una
decisión de contrato de datos que no corresponde tomar unilateralmente
dentro de un cierre de motor de informes. La API de `build_candidate_
report` ya está lista y probada con `WCSSolution`/`ZeropointFit`
reales (`fit_wcs`/`fit_zeropoint`, los motores reales, no simulados);
conectar la GUI es la continuación natural una vez se decida la
persistencia.

## 4. `reporting/observation_report.py` -- informe agregado

`build_observation_report(observation, candidates, *, pipeline_version="")`:
NO vuelve a ejecutar ningún motor -- cuenta y agrega lo que cada
`Candidate` recibido ya trae. Cinco secciones: Resumen (candidatos por
`identification_state`/`review_state`), Calidad (candidatos por
`overall_level`, artefactos marcados), Anomalías (candidatos por
dimensión disponible + significancia máxima real, gráfica de barras),
Evidencia (candidatos que superan el gate científico real, top 10 por
`priority_index` real), Procedencia. Honesto en cada rama vacía: sin
observación adjunta, sin candidatos, sin ninguna dimensión de anomalía
evaluada -- cada caso lo dice explícitamente.

GUI: **Descubrimiento -> "Generar informe de observación..."** -- con
más de una observación en la sesión, pregunta cuál (`QInputDialog.
getItem`); guarda vía `QFileDialog` con el mismo patrón ya establecido
(éxito -> barra de estado, error real -> `QMessageBox.critical`).

## Tests

- `tests/unit/diagnostics/` (10 nuevos): `flag_outliers` con 0/1/varios
  puntos, valores idénticos (nunca falso positivo), un atípico real,
  varios atípicos, umbral más laxo; `build_residual_diagnostic` rechaza
  entrada vacía, estadísticas correctas contra un cálculo independiente,
  atípico real detectado.
- `tests/unit/reporting/test_models.py` (+2): `outlier_indices` fuera de
  rango rechazado; válido aceptado.
- `tests/unit/visualization/test_charts.py` (+2): `kind="residual"` con
  y sin atípicos produce PNG real.
- `tests/unit/reporting/test_candidate_report.py` (+3): astrometría y
  fotometría muestran residuales reales cuando se les da un
  `WCSSolution`/`ZeropointFit` real (construido con `fit_wcs`/
  `fit_zeropoint`, los motores reales); ambas secciones siguen honestas
  sin ellos.
- `tests/unit/reporting/test_observation_report.py` (7 nuevos): conteos
  reales contra candidatos reales de `run_generic_discovery`, cambio de
  estado de revisión reflejado, anomalías agregadas correctamente,
  ranking por prioridad real, honestidad en cada caso vacío.
- `tests/gui_smoke/test_qt_app_observation_report_smoke.py` (2 nuevos):
  el menú produce un HTML real desde una corrida real de Discovery; sin
  observaciones, avisa en la barra de estado en vez de abrir el diálogo.

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **659 passed, 21 skipped, 1 xfailed** (antes: 635) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **114 passed** (antes: 112) |

**Datos reales**: las mismas 3 lights de M31 del cierre 43. Discovery
completo -> 46 candidatos reales. Informe de observación agregado real
generado y exportado (33 028 bytes, capturado visualmente): tabla de
estados de identificación (27 TRANSIENT_CANDIDATE, 18 UNMATCHED, 1
MOVING_SOURCE_CANDIDATE, suma exacta 46), 28 candidatos superan el gate
científico real, gráfica de barras de anomalía máxima por dimensión
(morfológica/temporal/astrométrica, con valores reales hasta 11.14
sigma). Residuales reales de astrometría/fotometría verificados sobre
un `WCSSolution`/`ZeropointFit` construidos con los motores reales
(`fit_wcs`/`fit_zeropoint`) -- capturado visualmente: el punto atípico
real aparece marcado en rojo con "x" en la gráfica, exactamente el
índice que `flag_outliers` señaló.

## Alcance todavía no cubierto (sin cambios respecto al cierre 43)

Export solo a HTML (CSV por tabla ya trivial vía `Table.to_csv`, PDF
requiere una dependencia nueva no evaluada); sin dominios dedicados de
fotometría/astrometría/espectroscopía/física/discovery más allá de lo
que ya aparece dentro del informe de candidato/observación; sin
`Spectrum` como sujeto de informe propio (no existe ese modelo de
dominio unificado todavía -- espectroscopía sigue siendo pasos
independientes: trace/wavelength/fluxcal/continuum, sin un resultado
combinado). La conexión GUI de `wcs_solution`/`zeropoint_fit` queda
pendiente de una decisión de persistencia, no de código de informes.

## Cambio de motor

Bloque de Visualización/Informes/Exportación (v1 + esta extensión)
terminado con lo que hoy tiene sentido real: contrato completo, tres
tipos de gráfica reales, informe de candidato y de observación,
diagnóstico de residuales reutilizable, todo validado con datos
sintéticos y con M31 real. Disponible para el siguiente motor cuando el
usuario lo indique.
