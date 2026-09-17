# 43 — Construcción: Scientific Visualization & Reporting Engine (v1)

A diferencia de los cierres 36-42 (conectar código ya existente que
estaba desconectado), este es un motor **nuevo**: no había ningún
código previo que "cerrar". El encargo lo definió así explícitamente:
*"OBJETIVO SIGUIENTE — Scientific Visualization & Reporting Engine...
convertir RESULTADO CIENTÍFICO en GRÁFICA + TABLA + DIAGNÓSTICO +
ESTUDIO + INFORME + EXPORTACIÓN"*, con una arquitectura sugerida (no
obligatoria: *"lo importante es el contrato"*) y una restricción central
explícita: *"No quiero que sea 'un módulo para hacer gráficas bonitas'...
la gráfica debe ser una representación del análisis real, no una capa
decorativa."*

Dado el alcance completo que el encargo sugiere (8 dominios:
image/photometry/astrometry/temporal/motion/spectroscopy/physics/
discovery), esta v1 construye **una rebanada vertical completa** --
el "estudio científico completo" de un `Candidate`, con sus 13
secciones -- como prueba arquitectónica real, en vez de esbozos
superficiales en los 8 dominios. El resto queda documentado como
trabajo futuro (ver "Alcance no cubierto" al final).

## Decisión de arquitectura

**`ScientificResult`**: contrato genérico, agnóstico de motor, que
convierte cualquier resultado científico tipado (`Candidate` hoy) en
una lista ordenada de `ReportSection` -- cada una con campos
clave/valor (`ReportField`), tablas (`tables.table.Table`, ya
existente, reutilizado sin cambios) y series graficables (`DataSeries`).
Deliberadamente una VISTA construida a partir de los contratos ya
tipados de cada motor, nunca su reemplazo -- mismo principio que ya
regía la relación entre `Table` y las mediciones de cada motor.

**Cadena real, no decorativa**: cada sección se construye leyendo
directamente los campos ya medidos del `Candidate` (S/N, FWHM, flujo,
vector de anomalía, cadena de evidencia...) -- nunca se recalcula ni se
simula nada para "rellenar" una gráfica. Cuando un motor no corrió
sobre este candidato (WCS por imagen, física en modo genérico), la
sección lo dice explícitamente ("NO DISPONIBLE (motivo concreto)") en
vez de dejar un hueco silencioso o inventar un valor -- extensión
directa del principio de honestidad epistémica que ya regía
`Quantity.NOT_AVAILABLE` a nivel de informe completo.

**Brecha de datos encontrada y cerrada**: `TemporalEvidence`/
`MotionEvidence` (cerrados en el informe 42 con `Provenance`) solo
llevaban el resultado AJUSTADO (pendiente, significancia) -- no los
puntos medidos que una curva de luz o una trayectoria real necesitan
dibujar. Se añadieron `TemporalEpoch`/`MotionEpoch` (modelos nuevos,
inmutables, con su propio `to_dict`/`from_dict`) como campo `epochs`
en ambos modelos, poblados en el punto exacto donde cada motor ya tenía
esos puntos (`analyze_motion`/`analyze_variability`), con filtrado
idéntico al que cada motor ya aplicaba internamente -- los puntos que
se grafican son EXACTAMENTE los que el motor usó, nunca una copia
ingenua del input crudo que el motor pudo haber descartado.

## Componentes construidos

| módulo | responsabilidad |
|---|---|
| `reporting/models.py` | `DataSeries`, `ReportField`, `ReportSection`, `ScientificResult` (el contrato) |
| `reporting/candidate_report.py` | `build_candidate_report(candidate, observation=None, ...)`: las 13 secciones reales |
| `visualization/charts.py` | `render_series`/`render_anomaly_vector`: `DataSeries` real -> PNG real (Matplotlib, backend `Agg` fijo) |
| `export/html.py` | `render_html`/`export_html`: `ScientificResult` -> HTML autocontenido (gráficas embebidas en base64, sin CSS/JS externo) |

**Las 13 secciones** (mismo orden que el caso de estudio del encargo,
APS-000124): Observación, Calidad, Astrometría, Fotometría, Morfología,
Temporal (curva de luz real, línea con barras de error), Movimiento
(trayectoria real, dispersión con primera/última época resaltadas),
Física, Anomalías (barras categóricas por dimensión disponible),
Evidencia, Catálogos, Procedencia, Revisión humana.

**Tres tipos de gráfica** (`DataSeries.kind`): `"line"` (curva de luz,
con barras de error cuando hay incertidumbre real), `"scatter"`
(trayectoria RA/Dec, primera época en verde / última en rojo),
`"bar"` (vector de anomalía, solo las dimensiones con evidencia real --
`x_categories` lleva la etiqueta real de cada barra, `x` sigue siendo
numérico `0..n-1` para no romper el contrato con las demás series).
`render_anomaly_vector` devuelve `None` (no una gráfica vacía) cuando
ningún eje tiene evidencia disponible.

## GUI

Botón **"Generar informe científico..."** en el detalle de candidato
(`candidate_detail_widget.py`), junto a Conservar/Marcar/Descartar --
abre `QFileDialog.getSaveFileName` (mismo patrón que "Exportar tabla a
CSV"/"Guardar sesión") y llama a `build_candidate_report` +
`export_html`. Éxito: señal `report_generated(path)` hasta la barra de
estado de `MainWindow` (este widget vive en una subventana MDI, sin
barra de estado propia). Error real (p. ej. disco lleno, permisos):
`QMessageBox.critical` con el motivo -- nunca un éxito fingido.

**Error real de diseño detectado y corregido durante la validación**: la
primera versión mostraba un `QMessageBox.information` bloqueante en
éxito. Bajo Xvfb (sin nadie que pulse el diálogo) esto colgaba el
proceso indefinidamente -- se encontró exactamente así, al ejecutar la
prueba de humo GUI y observar que el proceso seguía vivo sin avanzar
tras varios minutos. Corregido con la señal `report_generated` en vez
del diálogo modal, verificado con la misma prueba (que ahora además
comprueba que el mensaje llega a la barra de estado).

## Tests

- **Unit (`tests/unit/reporting/`, 21 nuevos):** `test_models.py` (7:
  validación de `DataSeries`, búsqueda de sección, `to_dict`) +
  `test_candidate_report.py` (14: las 13 secciones contra un `Candidate`
  real de `run_generic_discovery`, honestidad NO DISPONIBLE en
  astrometría/física/temporal/movimiento sin evidencia, series reales
  con evidencia real adjunta vía los motores reales).
- **Unit (`tests/unit/visualization/test_charts.py`, 7 nuevos):** cada
  tipo de gráfica produce un PNG real (cabecera `\x89PNG`, tamaño no
  trivial), dos series distintas producen imágenes distintas,
  `render_anomaly_vector` nunca fabrica una gráfica sin evidencia real.
- **Unit (`tests/unit/export/test_html.py`, 7 nuevos):** HTML
  autocontenido (sin `http://`/`<link`/`<script`), campos/tablas/notas
  reales presentes, orden de secciones respetado, `export_html` escribe
  a disco de verdad.
- **Integration (`tests/integration/test_reporting_pipeline.py`, 2
  nuevos):** cadena completa `Candidate` real (con evidencia temporal/
  de movimiento/de anomalía real adjunta) -> `build_candidate_report`
  -> `render_html`/`export_html`, confirmando 3 gráficas embebidas y
  consistencia con los datos reales del candidato origen.
- **GUI smoke (`tests/gui_smoke/test_qt_app_report_smoke.py`, 2
  nuevos):** el botón produce un HTML real en disco desde un candidato
  real de Discovery; un fallo real de escritura (directorio en vez de
  archivo) muestra `QMessageBox.critical`, nunca un éxito fingido.

Ningún test se conforma con "no lanza excepción": cada uno verifica
contenido real (bytes PNG válidos, texto HTML real, valores que
coinciden con los del candidato origen).

## Validación

| conjunto | comando | resultado |
|---|---|---|
| Unit + integración + regresión | `pytest tests/ --ignore=tests/gui_smoke` (venv `aps-test`) | **635 passed, 21 skipped, 1 xfailed** (antes: 597) |
| GUI smoke completa | `xvfb-run pytest tests/gui_smoke/` (venv `aps-gui`) | **112 passed** (antes: 110) |

**Datos reales utilizados:** las 3 lights reales de M31 ya usadas en el
cierre 42 (`Light_M31_300s_0001/0002/0003.fit`, Bayer RGGB, WCS SIP,
`DATE-OBS` real). Discovery completo sobre las 3 épocas: 46 candidatos
reales, 39 con `motion_evidence`/`temporal_evidence` real (>= 2 épocas).
Se generó el informe completo del candidato con más evidencia
disponible (`...IMG002-PT-00003`: 3 épocas de movimiento, 3 de
variabilidad, 3 dimensiones de anomalía) -- 13 secciones, 3 gráficas
reales embebidas (curva de luz, trayectoria, vector de anomalía),
verificadas visualmente con captura de pantalla real vía Playwright/
Chromium sobre el HTML exportado (`/tmp/informe_M31_real.html`,
117 248 bytes): layout correcto, gráficas legibles, texto NO DISPONIBLE
en rojo cursiva para las secciones sin datos, tablas con datos reales.

**Limitaciones conocidas (alcance no cubierto por esta v1):**

- Solo el dominio Candidato (13 secciones). Los otros 7 dominios que
  sugiere el encargo (visualización dedicada de fotometría,
  astrometría, espectroscopía, física, discovery a nivel de
  observación) quedan para una fase dedicada -- el contrato
  (`ScientificResult`/`DataSeries`/`ReportSection`) ya está listo para
  extenderse sin cambios de forma.
- Exportación solo a HTML. CSV por tabla ya es posible hoy mismo
  reutilizando `Table.to_csv` directamente sobre cualquier tabla de una
  sección (`report.section(key).tables[i].to_csv(path)`) -- no se
  construyó un exportador CSV dedicado por informe porque el mecanismo
  ya existe y no requiere código nuevo. PDF no se abordó (dependencia
  nueva no evaluada).
- Sin diagnóstico agregado multi-candidato (p. ej. tabla resumen de
  todos los candidatos de una observación) -- esta v1 es un informe por
  candidato, como pide el ejemplo del encargo (APS-000124).

## Cambio de motor

Motor nuevo construido y validado con datos reales (sintéticos + 3
épocas reales de M31). Disponible para pasar al siguiente motor, o
para extender esta v1 a los dominios restantes, cuando el usuario lo
indique.
