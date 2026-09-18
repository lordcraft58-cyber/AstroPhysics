# AstroPhysics Suite — Fase 3: Eliminación de Duplicados y Legado Confirmado

Continuación de `03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md`. Esta fase aplica, con tests de regresión primero, las acciones que la Fase 2 dejó identificadas y acotadas. No es una refactorización (eso es la Fase 6): es limpieza quirúrgica de lo que ya se había demostrado, con evidencia exhaustiva, muerto o incorrecto.

## 1. Metodología seguida

1. Se instaló un entorno real (Python 3.11.15 + numpy/scipy/astropy/photutils/matplotlib/openpyxl/pytest, ver `requirements-test.txt`) para poder **ejecutar** el código, no solo leerlo — la auditoría de las Fases 1-2 fue de lectura estática; esta fase se apoya además en comportamiento real verificado.
2. Se escribieron primero los tests de regresión (`tests/`) que fijan el comportamiento a preservar, siguiendo la disciplina "test-first" que el propio plan (`02-ARQUITECTURA-OBJETIVO-Y-PLAN.md`, Fase 3) exige antes de tocar el monolito.
3. Se aplicaron los cambios mínimos necesarios.
4. Se ejecutó la suite completa (tests nuevos + `selftest()` embebido) contra el resultado, y se comparó contra una ejecución de control sobre el archivo **sin modificar** (`git show` de la Fase 1) para descartar que cualquier fallo observado fuera una regresión introducida aquí.

## 2. Corrección del hallazgo P0 (Fase 1, sección 1)

Se eliminó el único backslash dentro de una expresión f-string (`legacy/.../write_html_report`, antes L5734) — el defecto que impedía que el archivo se importara en Python 3.10/3.11. La corrección precalcula el fragmento HTML condicional en una variable simple en vez de anidar comillas escapadas dentro de `{...}`; el HTML producido es byte-idéntico al original.

**Verificado:** el archivo ahora parsea (`ast.parse`) correctamente bajo Python 3.10, 3.11, 3.12 y 3.13, y `write_html_report()` genera un informe HTML real y correcto en la suite de tests (`test_python_compatibility.py`, `test_embedded_selftest.py`).

## 3. Corrección del bypass de consistencia científica (Fase 1 §7.2, Fase 2 §1)

`analyze_series_with_ai()` llamaba directamente a `analyze_pair_core()`, saltándose `analyze_pair_with_consistency()` y con ello los siete bloques de enriquecimiento que ese wrapper añade: `scientific_consistency`, `uncertainty_budget`, `literature_comparison`/`literature_zscores`, `anomalies`, `qc_summary`, `provenance` y `physical_maps`. Se cambió la llamada para que use `analyze_pair()` — la API pública única del módulo — con los mismos argumentos.

**Verificado:** `tests/regression/test_analyze_series_consistency.py` confirma, tanto para `analyze_series_with_ai` como para el conjunto completo de funciones de nivel de módulo, que **ninguna** ruta de ejecución llama a `analyze_pair_core` salvo `analyze_pair_with_consistency` — cerrando la clase de bug (rutas paralelas con contratos distintos) de forma estructural, no solo puntual.

## 4. Conexión de la suite de regresión v46 al `selftest()` (Fase 2 §1.5)

`_v46_regression_tests()` — que valida `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine` y `discovery_v46()`, es decir, el núcleo del futuro Evidence Engine — existía pero `selftest()` no la invocaba. Se añadió la llamada correspondiente, siguiendo el mismo patrón usado para `_v43_scientific_hardening`/`_v45_regression_tests`.

Se eliminó `_v44_regression_tests()`: al inspeccionarla se confirmó que era un alias de dos líneas (`return _v45_regression_tests()`) sin contenido propio — no una suite distinta con cobertura única, como se había supuesto de forma conservadora en la Fase 2. Se corrige aquí esa caracterización.

**Verificado:** `[OK] v46: physical constraints/spatial/temporal/evidence engine suite` en la ejecución real de `selftest()`, ahora cubierto también por `tests/regression/test_embedded_selftest.py`.

## 5. Eliminación de las 17 entidades muertas restantes

De las 23 entidades sin ninguna referencia identificadas en la Fase 2, se eliminaron 17 (más `_v44_regression_tests`, recalificada en el paso anterior). Se conservaron deliberadamente 5, documentadas explícitamente en `tests/architecture/test_dead_code.py` para que no se borren en una limpieza futura sin pasar por su integración correspondiente:

- `check_hardware`, `update_check_https`, `download_verified_update`, `launch_verified_installer` — el subsistema completo de diagnóstico/actualización verificada (Fase 1 §9): código correcto, solo pendiente de cablearse en la Fase 7-9.
- `FilamentDetectionStrategy` — el `Protocol` que documenta el contrato de las estrategias de detección de filamentos; su destino es convertirse en un contrato verificado en la Fase 4, no desaparecer.

Eliminadas (con su clúster, cuando aplicaba):

| Entidad | Nota |
|---|---|
| `launch_gui_legacy` + `_QueueLogHandler` | ~1000 líneas; la segunda solo era usada por la primera. GUI duplicada eliminada por completo — la única `launch_gui()` activa queda sin ambigüedad. |
| `_profile_selection_score` + copia antigua de `select_optimal_profile_candidates` | La implementación viva (con diversidad espacial) queda como única. |
| `resolve_object_center_legacy` | Casi-duplicado de nombre de `resolve_object_center` (viva). |
| `detect_point_sources_legacy` | Casi-duplicado de nombre de `_detect_point_sources_legacy` (viva, usada como fallback real dentro de `detect_point_sources`) — el par de nombres que solo difería en un guion bajo. |
| `estimate_field_center_from_gaia`, `gaia_distance_pc` | Helpers de astrometría/distancia sin caller. |
| `estimate_remnant_radius_uncertainty` | Sin caller. |
| `FITSQuality` | Dataclass sin uso. |
| `_survey_infer_object` | Sin caller (superseded por `infer_target_from_paths`). |
| `robust_query_simbad_field` | Ruta SIMBAD alternativa sin caller. |
| `load_mappings_grid` | Función libre redundante con `MappingsGridLoader`. |
| `ModelParameter`, `ModelFit` | Dataclasses sin uso (`ModelComparisonEngine` usa `ParameterEstimate`). |
| `compute_color_color_diagram` | Stub no funcional, propio docstring lo admitía. |
| `luminosity_distance` | Sin caller; se limpió también la mención residual en el changelog embebido (`audit_report`). |
| `FilterResponse` + `build_filter_response` | Clúster muerto completo. |

**Resultado:** el archivo pasó de 14.312 a 13.002 líneas (−1.310 líneas, −9.2%), sin ningún cambio de comportamiento observable.

## 6. Suite de tests añadida

```
tests/
├── conftest.py                                    # puente de importación hacia legacy/ (temporal, hasta Fase 6)
├── architecture/
│   └── test_dead_code.py                          # guarda: lo eliminado no vuelve; lo conservado-sin-cablear no desaparece
└── regression/
    ├── test_python_compatibility.py                # guarda del hallazgo P0
    ├── test_analyze_series_consistency.py          # guarda del bypass de consistencia científica
    ├── test_historical_contracts.py                # Background.bkg y Nx3 array, contra datos sintéticos reales
    └── test_embedded_selftest.py                   # conecta selftest() a CI/pytest
```

**Resultado de la ejecución completa:** `13 passed` (pytest, Python 3.11.15, dependencias reales). Se descubrió además, por comparación de control contra el archivo sin modificar, una falla preexistente y no relacionada (`load_fits` no preserva `np.memmap` con la versión de astropy usada en este entorno) — documentada explícitamente como conocida en `test_embedded_selftest.py` y candidata a investigarse en la Fase 6 al auditar el rendimiento de lectura FITS, no a esta fase.

## 7. Qué queda para la Fase 4

- Formalizar `FilamentDetectionStrategy` como contrato verificado (no solo documentado).
- Diseñar los contratos de datos versionados (`Observation`, `Detection`, `CharacterizationResult`, etc.) usando como punto de partida las firmas ya documentadas en `03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md`, sección 5.
- Definir el vocabulario único de estados de identificación, resolviendo la fragmentación de tres vocabularios descrita en la Fase 1 §8.1.
