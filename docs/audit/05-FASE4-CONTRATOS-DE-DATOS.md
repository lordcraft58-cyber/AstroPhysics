# AstroPhysics Suite — Fase 4: Contratos de Datos y Arquitectura Objetivo

Continuación de `04-FASE3-DUPLICADOS-Y-LEGADO-ELIMINADOS.md`. Esta fase entrega el paquete `astrophysics_suite/` -- la primera implementación real de la arquitectura objetivo descrita en `02-ARQUITECTURA-OBJETIVO-Y-PLAN.md` -- con los contratos de datos versionados que consumirán todos los motores a partir de la Fase 6, y el vocabulario único que resuelve la fragmentación de estados descrita en la Fase 1 (sección 8.1).

No se toca `legacy/` salvo dos líneas (ver sección 5). Esta fase es aditiva y verificable de forma independiente: todo lo que aquí se construye tiene sus propios tests, y uno de ellos (`test_legacy_adapter.py`) ejecuta el pipeline heredado real para demostrar que el esquema nuevo es compatible con datos reales, no solo con un diagrama.

## 1. Dónde vive esto y por qué

`astrophysics_suite/` es el paquete raíz de la arquitectura objetivo (§1 de `02-...`), sembrado con dos subpaquetes:

```
astrophysics_suite/
├── core/            # ValueKind, IdentificationState, ReviewState, ArtifactKind,
│                     # MorphologyClass, QualityLevel; Quantity; Provenance
└── models/          # Observation, Detection, CharacterizationResult, PhysicalInference,
                      # AnomalyVector, TemporalEvidence, MotionEvidence, EvidenceChain,
                      # Candidate, Project, y el adaptador legacy_adapter.py
```

`core/` no depende de ningún motor concreto; todo lo demás depende de `core/`, nunca al revés -- es la misma regla de dependencia de capas que `02-...` exige para el resto de la arquitectura, aplicada aquí primero porque es la base sobre la que se construirá todo lo demás.

## 2. Las dos piezas fundamentales: `Quantity` y el vocabulario único

### 2.1 `Quantity` -- por qué una sola clase reutilizada en todos los motores

El código heredado ya tenía la disciplina correcta de forma dispersa: `estimate_shock_velocity` declara "modelodependiente" en su propio docstring; `measure_proper_motion` marca su resultado como `"PROXY OBSERVACIONAL"`; el motor v46 declara explícitamente `"priority_index_is_not_probability": True`. Pero cada función inventaba su propia mezcla de campos `*_err`/`*_state`/`*_method`. `Quantity` (`core/quantity.py`) es ese patrón hecho un solo tipo, reutilizado en `CharacterizationResult`, `PhysicalInference`, `AnomalyVector`, `Candidate` y `EvidenceItem`:

```python
Quantity(value, error, unit, kind: ValueKind, method, reference, notes)
```

`ValueKind` tiene exactamente cinco valores -- `OBSERVED`, `PROXY`, `MODEL_INFERENCE`, `HYPOTHESIS`, `NOT_AVAILABLE` -- y operacionaliza literalmente el principio que el encargo pide para el Physical Engine ("es fundamental distinguir una medición directa, un observable, un proxy, una inferencia de modelo y una hipótesis física"). No es una convención de nombres de string que alguien pueda olvidar seguir: `Quantity.__post_init__` **rechaza construirse** si el valor es `NaN`/`inf` bajo cualquier `kind` que no sea `NOT_AVAILABLE`, y rechaza llevar un `value` numérico bajo `NOT_AVAILABLE`. Es decir: la ambigüedad que el encargo pide evitar ("cuando no haya WCS o calibración fotométrica, el resultado debe indicarlo explícitamente y no inferir más de lo que los datos permiten") queda imposible de expresar por accidente -- no se puede construir un `Quantity` que diga a la vez "no disponible" y "aquí tienes un número".

### 2.2 El vocabulario único de `IdentificationState`

`core/enums.py` fija los siete estados exactos que pidió el encargo: `KNOWN`, `KNOWN_VARIANT`, `UNMATCHED`, `ANOMALOUS`, `TRANSIENT_CANDIDATE`, `MOVING_SOURCE_CANDIDATE`, `DISCOVERY_REVIEW`. A partir de ahora es el **único** vocabulario válido para el estado de identificación de un `Candidate` -- sustituye a los tres que la Fase 1 encontró conviviendo sin reconciliar (`"OBSERVABLE"/"NO DISPONIBLE"` genérico; `"SCIENCE_CANDIDATE"/"ARTIFACT_REJECTED"/"KNOWN_GAIA"/...` del Discovery Workspace; y el vocabulario pedido por el encargo, que hasta ahora no existía como tal en ningún sitio ejecutable).

Se creó además `ArtifactKind` (13 valores, tomados literalmente de la lista del encargo: ruido, hot pixel, rayo cósmico, saturación, defecto de PSF, reflejo, gradiente, donut, error de registro, residuo de stacking, artefacto de procesado, traza de avión/satélite, otro) y `MorphologyClass` (12 valores: puntual, extendida, blob, filamento, arco, concha, compacta, elongada, doble, halo, jet, condensación) -- las dos taxonomías que el encargo pide para el Artifact Rejection Engine y el Detection Engine, respectivamente, y que hoy solo existían como comentarios de prosa en el encargo, no como tipos verificables.

**Deliberadamente NO se mezclan** los estados temporales ("¿apareció? ¿desapareció? ¿es variable?") dentro de `IdentificationState`. El encargo menciona `VARIABLE_SOURCE_CANDIDATE`/`MORPHOLOGY_CHANGE_CANDIDATE` como salidas del Temporal Engine junto a `TRANSIENT_CANDIDATE`/`MOVING_SOURCE_CANDIDATE` (que sí son parte del vocabulario de identificación), pero son ejes distintos: uno describe la relación con catálogos, el otro describe comportamiento temporal medido. Fusionarlos en un solo enum habría recreado, dentro del código nuevo, el mismo problema de vocabularios mezclados que esta fase existe para resolver. En su lugar, `TemporalEvidence` (`models/temporal.py`) transporta el comportamiento medido (aparición, desaparición, cambio de brillo/morfología/color, `variable_candidate: bool`) como evidencia; qué `IdentificationState` final le corresponde a un `Candidate` con esa evidencia es una decisión de la orquestación del Discovery Engine (Fase 7), no algo que el modelo de datos deba precocinar.

## 3. Los ocho modelos

| Modelo | Archivo | De qué motor objetivo viene |
|---|---|---|
| `Observation` (+ `ImageRef`) | `models/observation.py` | Entrada del pipeline. Metadata cruda, sin `Quantity` -- no es un resultado científico. |
| `Detection` (+ `SkyPosition`, `MorphologySummary`) | `models/detection.py` | Detection Engine. Lo mínimo antes de rechazo de artefactos/identificación. |
| `CharacterizationResult` | `models/characterization.py` | Characterization Engine. Campos comunes explícitos (tamaño, área, FWHM, elongación, brillo superficial, movimiento propio, variabilidad) + `band_flux`/`band_ratios`/`color`/`extra` como diccionarios de `Quantity` para no forzar un esquema único entre fuentes puntuales y extendidas. |
| `PhysicalInference` | `models/physical.py` | Physical Engine. `parameters: dict[str, Quantity]` -- cada parámetro lleva su propio `ValueKind`, porque dentro de una misma inferencia una entrada puede ser `OBSERVED` (p. ej. una distancia asumida) y una salida `MODEL_INFERENCE` (p. ej. la edad derivada). |
| `AnomalyVector` | `models/anomaly.py` | Anomaly Engine. Siete dimensiones independientes (`photometric`, `morphological`, `spectral`, `temporal`, `astrometric`, `spatial`, `physical`), cada una `Quantity \| None`. No existe ningún campo "score". |
| `TemporalEvidence` / `MotionEvidence` | `models/temporal.py` | Temporal Engine. Evidencia medida, no un estado -- ver §2.2. |
| `EvidenceChain` (+ `EvidenceItem`) | `models/evidence.py` | Evidence Engine -- el núcleo conceptual del producto (ver §4). |
| `Candidate` (+ `CatalogMatch`, `CatalogQuery`, `ArtifactCheck`, `QualitySummary`, `AIAssessment`, `ReviewNote`) | `models/candidate.py` | Candidate Engine -- ver §5. |
| `Project` | `models/project.py` | Contenedor persistente ligero; el almacenamiento real es trabajo de Fase 6/7. |

Todos siguen la misma disciplina: `frozen=True` (inmutables), `schema_version` explícito, `to_dict()`/`from_dict()` simétricos (probado con tests de roundtrip para cada uno), y ningún campo numérico "suelto" -- todo lo que es una medición o inferencia es un `Quantity`, nunca un `float` desnudo sin procedencia.

## 4. `EvidenceChain`: independencia de evidencias como código, no como intención

`EvidenceChain.independent_evidence_count` **no cuenta piezas de evidencia** -- cuenta **motores distintos** que aportan al menos una pieza a favor (`supporting_engines`, deduplicado). Dos piezas de evidencia del mismo motor nunca pueden, por construcción, hacer parecer un candidato mejor respaldado de lo que está. `scientific_candidate_gate` exige `independent_evidence_count >= minimum_independent_evidence` (2 por defecto) -- el mismo umbral que ya usaba `DiscoveryEvidenceEngine` en el código heredado (`docs/audit/01-...`, sección 13.2), ahora como una propiedad calculada e imposible de falsear manualmente (no es un campo que un motor pueda escribir directamente; se deriva siempre de `items`).

`human_verification_required` es `True` por defecto y no hay ningún camino en el modelo para que un `Candidate` se autodeclare descubierto: `test_candidate_never_declares_discovery` fija explícitamente que `IdentificationState` no contiene ni `DISCOVERY_CONFIRMED` ni `NEW_OBJECT` ni nada equivalente, y que `Candidate.mark_reviewed()` es exclusivamente una acción humana registrada con autor y nota.

## 5. `Candidate`: inmutable, con historial de revisión completo

`Candidate.mark_reviewed(new_state, author, note, reviewed_at)` no muta el candidato -- devuelve uno nuevo, con la nota añadida a `review_notes`. El original permanece intacto. Para un proyecto científico "pensado para conservarse durante años" (encargo original), perder por qué alguien descartó o conservó un candidato es tan grave como perder el candidato mismo; con este diseño es estructuralmente imposible perderlo por una sobreescritura accidental.

Se implementó además `models/legacy_adapter.py`, que traduce una fila real de `discovery_scan_observation()` (el pipeline heredado más reciente, ver `01-...` sección 6.3) a `Candidate`, incluyendo la tabla de correspondencia explícita `discovery_state`/`catalog_state`/`anomaly_state` → `IdentificationState` que antes no existía en ningún sitio del código (ver `identification_state_from_discovery_workspace_row`). Deliberadamente no se tradujo también la fila del pipeline OIII/Hα (`analyze_pair_core`): tiene un contrato de candidato distinto (física de choque, grids MAPPINGS) y traducirlo aquí de forma apresurada habría arriesgado un mapeo improvisado que la Fase 7 (unificación real de los tres pipelines) tendría que deshacer. Este adaptador se probó contra una ejecución **real** de `discovery_scan_observation()` sobre una imagen sintética (`test_adapter_handles_real_discovery_workspace_row`), no solo contra un diccionario inventado a mano.

## 6. Cambio adicional en `legacy/` (2 líneas)

Se cerró el pendiente que la Fase 3 dejó explícito: `FilamentDetectionStrategy` (el `Protocol` que documenta el contrato de `HessianFilamentStrategy`/`CannyFilamentStrategy`) ahora lleva `@runtime_checkable`. El contrato pasa de ser documentación no verificable a algo que se puede comprobar con `isinstance(strategy, FilamentDetectionStrategy)` -- verificado en `tests/regression/test_filament_strategy_protocol.py` contra las dos estrategias reales.

## 7. Decisiones explícitas que quedan documentadas para no repetirse

- **No se usó pydantic ni ninguna librería de validación externa.** Los `to_dict()`/`from_dict()` explícitos son más código que un decorador, pero son trazables campo a campo y no añaden una dependencia nueva a un producto que todavía no ha decidido su empaquetado final (Fase 9). Es una elección revisable, no un descuido: si en la Fase 6/7 el volumen de modelos crece mucho más, pydantic (u otra alternativa) debe reconsiderarse explícitamente, no adoptarse por inercia.
- **`Observation` no usa `Quantity`.** Es metadata de entrada, no un resultado de ningún motor -- mezclar ambos habría diluido el significado de "esto es lo que un motor concluyó, con su incertidumbre y procedencia".
- **El vocabulario temporal y el de identificación se mantienen separados** (§2.2) aunque el encargo los mencione en la misma frase -- es la aplicación directa del hallazgo central de la Fase 1 (no crear un cuarto vocabulario mezclado).
- **El adaptador legacy solo cubre un pipeline.** Cubrir los dos (o los tres, incluyendo el motor v46) de golpe es precisamente el trabajo de fusión que le corresponde a la Fase 7, no a esta.

## 8. Verificación

61/61 tests pasan (`pytest tests/`), incluidos los 13 de la Fase 3. Los nuevos 48 cubren: construcción e invariantes de `Quantity` (incluida la validación NaN/`NOT_AVAILABLE`), roundtrip de serialización de los ocho modelos y sus tipos auxiliares, inmutabilidad y acumulación de historial en `Candidate.mark_reviewed`, la lógica de independencia de evidencias de `EvidenceChain`, el contrato `runtime_checkable` de `FilamentDetectionStrategy`, y el adaptador legacy ejecutado contra una corrida real del pipeline heredado.

## 9. Qué queda para la Fase 5 / Fase 6

- Fase 5 (tests de regresión) ya tiene, de facto, un adelanto sustancial en esta fase (61 tests con pytest real); lo que falta allí es sobre todo la suite de integración de extremo a extremo y los smoke tests de GUI, que no tienen sentido hasta que exista una GUI nueva (Fase 8).
- Fase 6 debe decidir, motor por motor, cómo migrar la lógica de `analyze_pair_core`/`detect_discovery_sources`/etc. para que produzcan estos modelos directamente en vez de dicts -- este documento y `astrophysics_suite/models/` son el contrato que esa migración debe cumplir, no una sugerencia.
