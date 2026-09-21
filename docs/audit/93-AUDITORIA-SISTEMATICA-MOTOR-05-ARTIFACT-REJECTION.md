# 93 — Auditoría sistemática, motor 5/16: Artifact Rejection (re-auditoría)

Quinto motor de la fase de cierre sistemático. Ya se había cerrado bajo
el proceso anterior (informe 87, dos hallazgos reales corregidos: un bug
de visibilidad en la GUI y el último residuo de legado migrado). Esta
re-auditoría, bajo el checklist más estricto de la fase actual, encontró
un tercer hallazgo real: una duplicación de lógica entre
`discovery/pipeline.py` y `artifacts/morphology_screen.py` con un riesgo
de divergencia real, aunque inofensivo hoy.

## Mapa del motor (fase previa, sin tocar código)

**Motor científico**: `astrophysics_suite/artifacts/{artifact_screen,
morphology_screen}.py`. **Consumidor autoritativo**:
`discovery/pipeline.py` (Pase 1: filtro barato vía `classify_morphology`;
Pase 3: gate real vía `screen_detection`, ninguna detección se convierte
en `Candidate` sin pasarlo). **GUI**:
`qt_app/candidates/candidate_detail_widget.py::_section_quality_artifacts`
(arreglado en el informe 87, verificado aquí que sigue intacto).
**Tests (antes de este informe)**: `tests/unit/artifacts/
{test_artifact_screen,test_morphology_screen}.py` (17+5),
`tests/regression/test_morphology_screen_matches_legacy.py` (602),
`tests/gui_smoke/test_qt_app_candidates_smoke.py` (+1 del informe 87).

Se leyeron ambos archivos del motor científico completos y se verificó,
con `grep`, cada función pública de `morphology_screen.py` contra sus
consumidores reales en `discovery/pipeline.py`.

## Hallazgo y cierre

### `discovery/pipeline.py` duplicaba el mapeo estado->calidad de `morphology_screen.py`, con una entrada real de menos

`morphology_screen.py` expone `quality_check_for(detection)` --
construida explícitamente, según su propio docstring, para ser LA fuente
única de la conversión "estado de `classify_morphology`" ->
`QualityCheckItem`. Pero `discovery/pipeline.py` nunca la llamaba: tenía
su propia copia local del mapeo (`_QUALITY_LEVEL_FOR_STATE`, tres
entradas) y construía el `QualityCheckItem`/`QualitySummary.overall_level`
a mano con ella, en vez de con la función real.

La copia local le faltaba la entrada `ARTIFACT_REJECTED` que sí tiene
`morphology_screen._STATE_TO_QUALITY_LEVEL` (`QualityLevel.FAIL`).
**Inofensivo en la práctica** -- el Pase 1 descarta con `continue`
cualquier detección `ARTIFACT_REJECTED` antes de que llegue al punto
donde se construye `QualitySummary`, así que esa clave nunca se
consultaba -- pero es exactamente el tipo de duplicación que el propio
proyecto evita en otros sitios por principio (p. ej. `plate_solve.py`
reutiliza `pixel_scale_arcsec_per_px` de `instruments/optics.py` "una
sola implementación, nunca dos que puedan divergir", comentario textual
en ese archivo). Si `classify_morphology` ganara un estado nuevo en el
futuro, la copia local del pipeline habría podido lanzar un `KeyError`
real sin que nada lo hubiera anticipado -- y `quality_check_for`, ya
implementada y con tests propios desde el informe 87, tenía cero
consumidores de producción: exactamente el patrón "función real, sin
conectar" que motores anteriores de esta fase ya encontraron y cerraron
(`resolve_path` en IO/FITS, informe 89).

**Corregido**: `discovery/pipeline.py` ahora llama a
`quality_check_for(reference_detection)` directamente y deriva
`overall_level` del propio resultado (`morphology_check.level`), en vez
de mantener una copia local. Se eliminó `_QUALITY_LEVEL_FOR_STATE` por
completo, y los campos `morphology_state`/`morphology_reason` de
`_ProcessedSource` (que solo existían para transportar el resultado ya
calculado de `classify_morphology` hasta ese punto) también se
eliminaron -- `quality_check_for` ya recalcula lo mismo de forma barata
y determinista a partir del `Detection`, sin necesidad de transportarlo
por separado.

`artifact_checks_for(detection)` (la función hermana de
`quality_check_for`, misma migración) se revisó también: solo puede
producir un `ArtifactCheck` no vacío cuando `classify_morphology`
devuelve `ARTIFACT_REJECTED` -- pero ninguna detección con ese estado
llega jamás al punto donde `Candidate.artifact_checks` se construye (el
Pase 1 ya la descartó). Conectarla ahí sería una llamada que siempre
devuelve `()`, sin ningún efecto real -- no es un hueco que cerrar, es
una capacidad correctamente implementada y testeada sin caso de uso en
la arquitectura actual (ver "qué queda fuera" abajo).

Un test de integración nuevo
(`test_candidate_quality_matches_the_real_morphology_screen_single_source_of_truth`)
reconstruye, de forma independiente, la `Detection` de cada candidato
real producido por el pipeline y comprueba que `candidate.quality`
coincide EXACTAMENTE con lo que `quality_check_for`/`classify_morphology`
calculan por su cuenta -- la prueba que habría fallado si las dos copias
llegaran a divergir.

## Validación con datos reales

Pipeline genérico completo (`run_generic_discovery`, `threshold_sigma=6.0`)
sobre el mismo LIGHT real de M31 sin calibrar que usan los cierres
anteriores: **365 detecciones reales, 44 rechazadas por el gate, 321
candidatos reales** -- para los 321, `candidate.quality.checks` tiene
exactamente una entrada `"morphology_screen"`, y `overall_level` coincide
con su nivel, confirmado programáticamente contra datos reales (no solo
contra el campo sintético del test de integración).

## Qué queda fuera, documentado (no bloquea el cierre)

- **`artifact_checks_for`**: implementada, testeada
  (`tests/unit/artifacts/test_morphology_screen.py`), pero sin
  consumidor de producción posible en la arquitectura actual del
  pipeline (ver arriba) -- no es un hueco, es una función correcta sin
  caso de uso hoy, mismo tratamiento que `allow_first_plane` en el cierre
  de IO/FITS (informe 89).
- **REFLECTION, DONUT, GRADIENT, STACKING_RESIDUAL, PROCESSING_ARTIFACT,
  REGISTRATION_ERROR en una sola época**: siguen NO DISPONIBLE, decisión
  ya documentada y confirmada de nuevo en el informe 87 -- sin cambios.
- **`input_hashes` en la provenance de las detecciones**: el informe 87
  lo dejó anotado como abierto; ya se cerró en el informe 88 y se
  reconfirmó en la auditoría del motor de Detección (informe 92) -- no
  es un hueco de Artifact Rejection.

## Checklist de cierre (20 puntos)

| Punto | Estado |
|---|---|
| Implementación científica real | Sí -- `screen_detection` (gate autoritativo) + `classify_morphology` (filtro barato), ambos nativos desde el informe 87 |
| Entrada definida | Sí -- `Detection` + `CharacterizationResult` + `FieldStatistics` |
| Salida definida | Sí -- `ArtifactScreenResult`/`ArtifactCheck`/`QualityCheckItem` |
| Tipos coherentes | Sí -- dataclasses tipadas en todo el flujo |
| Unidades correctas | Sí -- px, arcsec, adimensional según el criterio, consistente |
| Incertidumbres cuando correspondan | Sí -- `ArtifactCheck.confidence` es un `Quantity` real, nunca inventado |
| Manejo explícito de datos faltantes | Sí -- cada criterio sin medida real se declara NO DISPONIBLE, nunca "limpio" por defecto |
| NOT_AVAILABLE cuando proceda | Sí -- 5 categorías sin criterio validado, declaradas explícitamente, mismo criterio en las dos re-auditorías |
| Provenance | Sí -- `Quantity.not_available`/`Quantity` real por comprobación; `input_hashes` de la detección de origen ya cerrado (informe 88) |
| Errores correctamente gestionados | N/A directo (sin operaciones de E/S ni red en este motor) |
| Funciona independientemente | Sí -- sin GUI, ver `tests/unit/artifacts/` |
| Conectado al motor anterior (Detection) | Sí -- consume `Detection`/`CharacterizationResult` reales |
| Conectado al siguiente (Characterization/Candidate) | Sí -- gate autoritativo antes de construir cualquier `Candidate`; `quality_check_for` ahora es la única fuente del `QualitySummary` (hallazgo cerrado en este informe) |
| GUI funcional | Sí -- checklist completo visible en el detalle de candidato (informe 87) |
| Guardado de resultados correcto | N/A -- no es un motor que guarde archivos por sí solo; su salida vive en `Candidate`, cuya persistencia ya cerró el motor de Persistencia de Sesión |
| Rutas de salida controladas por el usuario | N/A (mismo motivo) |
| Tests unitarios | Sí -- 22 (17+5, sin cambios de número) |
| Tests de integración | Sí -- 1 nuevo (`test_candidate_quality_matches_the_real_morphology_screen_single_source_of_truth`) que antes no existía |
| Test de regresión | Sí -- 602 contra legacy, sin cambios |
| Validación con datos reales/controlados | Sí -- LIGHT real de M31, 321 candidatos reales verificados, ver arriba |
| Documentación actualizada | Sí -- este informe |
| Ningún placeholder presentado como funcionalidad | Sí -- confirmado, sin excepciones |

## Validación de la suite completa

- `ruff check astrophysics_suite tests`: limpio.
- Unitaria + integración + regresión: **1692 passed** (antes: 1691, +1
  test nuevo), 24 skipped -- sin regresión.
- Humo GUI: sin cambios de código en `qt_app/` en este informe, no
  requiere nueva corrida (ya validada íntegra en el informe 91, 214
  passed; el fix de este informe está enteramente en la capa de ciencia).

## CHECKPOINT

```
MOTOR: Artifact Rejection
ESTADO: CERRADO
IMPLEMENTACIÓN: astrophysics_suite/artifacts/{artifact_screen,morphology_screen}.py
ENTRADA: Detection + CharacterizationResult + FieldStatistics (por imagen)
SALIDA: ArtifactScreenResult (checks + rejected) / QualityCheckItem, con confidence real por comprobación
GUI: sí (candidate_detail_widget.py -- checklist completo, arreglado en el informe 87, verificado intacto)
PROVENANCE: sí (Quantity real/not_available por comprobación; input_hashes de la detección de origen, cerrado en informe 88)
TESTS: 22 unitarios + 602 regresión + 1 integración nuevo = 625 tests directos del motor
TESTS PASADOS: 1692 (unit/integración/regresión en conjunto, sin fallos)
TESTS FALLIDOS: 0
VALIDACIÓN REAL: sí (LIGHT real de M31 sin calibrar, 365 detectadas / 44 rechazadas / 321 candidatos reales, quality.checks consistente en el 100%)
PROBLEMAS RESTANTES: ninguno bloqueante. Documentado fuera de alcance: artifact_checks_for sin caso de uso en la arquitectura actual (correcta, no un hueco); 5 categorías de artefacto siguen NO DISPONIBLE por falta de criterio validado (decisión ya documentada).
CONTRATO HACIA EL SIGUIENTE MOTOR (Characterization): Detection + CharacterizationResult que ya sobrevivieron el gate, con ArtifactScreenResult.checks listo para Candidate.artifact_checks -- exactamente lo que discovery/pipeline.py ya consume hoy.
```

## Cambio de motor

Artifact Rejection re-auditado y cerrado bajo el checklist de 20 puntos,
con un hallazgo real de duplicación corregido, testeado (unitario +
integración) y validado con datos reales. Siguiente en el orden fijo del
usuario: **Characterization**.
