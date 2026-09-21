# 87 — Cierre de Artifact Rejection

Quinto motor de la lista del usuario, tras Detection (informe 54). A
diferencia de IO/Reducción/Astrometría/Detección, el motor entero ya
estaba construido y cableado como **gate autoritativo** en
`discovery/pipeline.py` desde la Fase P0.3 (tarea 73): ninguna detección
se convierte en `Candidate` sin pasar antes por `screen_detection`
(`artifacts/artifact_screen.py`). La auditoría de este cierre no
encontró un motor a medio construir, sino dos huecos reales y concretos:
un bug de visibilidad en la GUI (información real que el motor ya
calculaba pero que nunca llegaba a verse) y el último residuo de código
heredado en la ruta de rechazo de artefactos.

## 1. El detalle de candidato nunca mostraba ningún check de artefactos (código muerto)

**El hueco**: `qt_app/candidates/candidate_detail_widget.py::_section_
quality_artifacts` iteraba `candidate.artifact_checks` y solo mostraba
una fila `if artifact.flagged`. Pero `screen_detection` calcula:

```python
rejected = any(check.flagged for check in checks)
```

y `discovery/pipeline.py` descarta la detección ENTERA (`continue`, sin
crear `Candidate`) en cuanto `screen.rejected` es `True`. Por
construcción, **ningún `Candidate` real puede tener jamás una
comprobación con `flagged=True`** -- si la tuviera, no existiría como
candidato. La condición `if artifact.flagged` era código muerto: la
sección "Calidad y artefactos" del detalle de cualquier candidato real,
desde que existe el motor, nunca mostró una sola fila de las 12
categorías de `ArtifactKind` que el motor sí evalúa (o marca
explícitamente como no evaluable) para cada uno.

**Confirmado con datos reales de M31** (ver validación abajo): de 370
candidatos reales producidos sobre el mismo LIGHT que ya usaron los
cierres anteriores, el 100% tiene 7 comprobaciones evaluadas y limpias
y 6 marcadas honestamente como no evaluables -- cero con `flagged=True`,
exactamente como predice la construcción del gate.

**El arreglo**: la sección ahora recorre TODAS las comprobaciones y
muestra, por categoría, si quedó limpia, no evaluable (con el motivo
real) o -- por si en el futuro algún llamador usa `screen_detection` sin
pasar por el gate -- marcada como artefacto:

```python
if artifact.confidence is None or not artifact.confidence.is_available:
    status = "no evaluable"
elif artifact.flagged:
    status = "ARTEFACTO"
else:
    status = "limpio"
```

## 2. Último residuo de legado en la ruta de rechazo de artefactos

**El hueco**: `artifacts/morphology_screen.py::classify_morphology`
(el filtro morfológico barato del Pase 1 de `discovery/pipeline.py`,
que descarta lo más extremo antes de gastar caracterización de píxeles
en basura evidente) seguía delegando en
`legacy...AstroPhysicsSuite_v57_3_COMMERCIAL._label_discovery_
morphology` -- el mismo patrón que doc 54 encontró y migró para
Detection.

**Auditoría de riesgo**: a diferencia de la fórmula de FWHM que
resultó estar rota en Detection, `_label_discovery_morphology` es una
cadena de 6 comparaciones directas sobre escalares ya medidos (área,
elongación, compactness, S/N de pico) -- sin ningún cálculo
geométrico/estadístico propio. Riesgo de migración bajo, pero sigue
siendo el ÚNICO import de `legacy` que queda en toda la ruta de
rechazo de artefactos, y produce directamente el tipo de salida propio
de este motor (`ArtifactCheck`).

**Lo hecho**: la misma cadena de umbrales, reproducida nativamente en
`morphology_screen.py`, verificada 1:1 contra el original ANTES de
quitar la delegación: `tests/regression/test_morphology_screen_
matches_legacy.py`, 601 combinaciones parametrizadas de área/elongación/
compactness/S·N que cruzan cada umbral real (8.0, 2.0, 4.0, 2.5, 0.18)
por ambos lados, más el caso de medición no finita -- coincidencia
exacta de `(state, reason)` en los 601 casos.

## Validación con datos reales

LIGHT de M 31 (300 s, mismo fotograma crudo sin bias/dark/flat que el
cierre de Detection), pipeline genérico completo de extremo a extremo
(`run_generic_discovery`, `threshold_sigma=5.0`):

| Magnitud | Valor real |
|---|---|
| Detecciones reales | 416 |
| Rechazadas por el filtro morfológico barato (Pase 1) | 0 |
| Rechazadas por `screen_detection`, el gate real (Pase 3) | 46 |
| Motivo real de las 46 rechazadas | 100% `COSMIC_RAY` (FWHM mucho más afilado que la PSF real del campo) |
| Candidatos reales resultantes | 370 |
| Candidatos con alguna comprobación `flagged=True` | 0 (imposible por construcción) |
| Comprobaciones reales evaluadas y limpias por candidato | 7 (SATURATION, NOISE, SATELLITE_OR_AIRPLANE_TRAIL, HOT_PIXEL, COSMIC_RAY, PSF_DEFECT, OTHER) |
| Comprobaciones honestamente no evaluables por candidato | 6 (REGISTRATION_ERROR -- requiere multiépoca; REFLECTION, DONUT, GRADIENT, STACKING_RESIDUAL, PROCESSING_ARTIFACT -- sin criterio validado con los datos disponibles) |
| Referencia de PSF real del campo | mediana 16.70 px, dispersión 0.34 px (45 fuentes de referencia en una imagen parcial de prueba) |

El 100% de rechazos reales por `COSMIC_RAY` es coherente con estar
analizando, igual que en el cierre de Detection, un LIGHT **crudo, sin
reducir**: sin corrección de rayos cósmicos previa (esa es tarea de
Reducción, motor 1, ya cerrado), el detector real encuentra impactos
puntuales mucho más afilados que cualquier estrella real -- exactamente
la señal que `COSMIC_RAY` existe para capturar.

Confirmado además con la prueba de humo GUI de extremo a extremo
(`test_candidate_detail_shows_the_real_artifact_checklist_not_just_
flagged_ones`): un análisis de Descubrimiento real sobre un campo
sintético, abrir el detalle del primer candidato real, y verificar que
aparecen filas "(limpio)" y "(no evaluable)" -- y ninguna
"(ARTEFACTO)", como corresponde a un candidato que sobrevivió al gate.

## Checklist del motor

| Fase | Estado |
|---|---|
| IMPLEMENTACIÓN | `artifacts/artifact_screen.py` (gate real, ya existía) + `artifacts/morphology_screen.py` (migrado de legacy en este cierre) |
| CONTRATO | `ArtifactCheck`/`ArtifactKind` (Fase 4), `ArtifactScreenResult`, `FieldStatistics` |
| GUI | `candidate_detail_widget.py::_section_quality_artifacts` -- ahora muestra el checklist real completo (arreglado en este cierre) |
| SALIDA | `Candidate.artifact_checks` (sin cambios de forma) |
| PROVENANCE | `ArtifactCheck.confidence` es un `Quantity` real con `Quantity.not_available(...)` honesto donde no hay criterio |
| UNIT TEST | `tests/unit/artifacts/test_artifact_screen.py` (17, ya existentes), `tests/unit/artifacts/test_morphology_screen.py` (5, ya existentes) |
| REGRESSION TEST | `tests/regression/test_morphology_screen_matches_legacy.py` (602, nuevas) |
| GUI SMOKE TEST | `tests/gui_smoke/test_qt_app_candidates_smoke.py` (+1, nueva) |
| FITS REAL | LIGHT de M 31 -- ver tabla arriba |
| CERRADO | sí |

Suite completa tras el cierre: **1685 pasadas, 24 saltadas, 1 xfailed**
(`aps-test`, +601 sobre el cierre anterior, casi todas del barrido
paramétrico de regresión) y **205 pasadas** de humo GUI (`aps-gui`,
+1). `ruff` limpio.

## Lo que sigue abierto en este motor

- **REFLECTION, DONUT, GRADIENT, STACKING_RESIDUAL, PROCESSING_
  ARTIFACT** siguen sin un criterio real que los evalúe -- decisión
  deliberada y documentada en el propio `artifact_screen.py` desde su
  construcción: ninguno de los observables que `photometry/quality.py`
  mide hoy por fuente basta para distinguirlos con rigor (algunos,
  como `STACKING_RESIDUAL`, necesitarían los fotogramas individuales
  del apilado, que esta ruta no recibe). Declarados NO DISPONIBLE,
  nunca "comprobado y limpio" -- confirmado con datos reales arriba.
- **`REGISTRATION_ERROR`** solo se evalúa en modo multiépoca (necesita
  dispersión de posición real que comparar); en una sola época se
  declara no disponible, como en la validación de arriba.
- **`input_hashes` sigue sin rellenarse** en la `Provenance` de las
  detecciones que alimentan este motor -- mismo hueco ya anotado en
  los informes 52/53/54, no específico de este cierre.
