# AstroPhysics Suite — Fase 7: Integración del Discovery Engine

Continuación de `08-FASE6-MOTORES-RESTANTES.md`. La Fase 6 dejó nueve motores extraídos y probados por separado; esta fase los **orquesta**: la ruta real `Observation → list[Candidate]` que el resto de todo este proceso de reingeniería ha estado construyendo hacia. Es la primera vez que el producto -- no un motor individual -- se puede ejecutar de principio a fin sobre datos reales.

## 1. Dos modos, honestos sobre lo que cada uno cubre hoy

### 1.1 Modo genérico (`discovery/pipeline.py::run_generic_discovery`)

Es el equivalente tipado del antiguo Discovery Workspace v57 (`discovery_scan_observation`, Fase 1 §6.3) -- agnóstico de tipo de objeto, no exige un par OIII/Hα. A diferencia del original, **no reimplementa su propia detección ni su propio cross-match**: usa los motores reales de la Fase 6 (`detection.point_sources`, `artifacts.morphology_screen`, `photometry.quality`, `catalogs.gaia`), cerrando exactamente el defecto arquitectónico central que la Fase 1 documentó como el hallazgo más importante de toda la auditoría -- tres pipelines de descubrimiento paralelos que no se hablaban entre sí.

Orden de ejecución, siguiendo la filosofía del encargo (IMÁGENES → DETECCIÓN → RECHAZO DE ARTEFACTOS → IDENTIFICACIÓN → CARACTERIZACIÓN → CANDIDATO): el rechazo de artefactos ocurre **antes** de que nada se considere candidato -- una detección `ARTIFACT_REJECTED` nunca produce un `Candidate`, ni siquiera uno marcado como rechazado. Esto es deliberado y distinto de cómo lo hacía el Discovery Workspace heredado (que sí generaba una fila `REJECTED_ARTIFACT` por cada artefacto): el encargo pide que el rechazo de artefactos actúe "antes de considerar algo un candidato científico", no que produzca candidatos-artefacto para descartar después.

Verificado de extremo a extremo con FITS sintéticos reales (`tests/integration/test_generic_discovery_pipeline.py`): escribe imágenes a disco, construye una `Observation` real, detecta fuentes reales con DAOStarFinder, las caracteriza, intenta identificarlas contra Gaia (cae honestamente en `DISCOVERY_REVIEW` por falta de WCS en el FITS sintético -- no se inventa una coordenada), y produce `Candidate` reales con roundtrip de serialización verificado. También cubre multibanda (dos imágenes, una `Observation`) y el caso sin fuentes (campo vacío → cero candidatos, no un error).

### 1.2 Modo especializado (choque OIII/Hα) -- compuesto, no conectado a píxeles todavía

`tests/integration/test_specialized_evidence_chain.py` demuestra que `physics.inference`, `anomaly.physical_tension` y `evidence.fusion` -- los tres motores de la Fase 6 más específicamente físicos -- **componen correctamente entre sí** sobre una misma fila de observables, y que el resultado se puede ensamblar en un `Candidate` completo con `physical_evidence` y `anomaly_evidence` poblados (algo que el modo genérico nunca produce, por no tener observables físicos). El test usa una tensión de temperatura post-choque real (∼449 000 K inferidos vs. una referencia deliberadamente alejada) para confirmar que la cadena completa -- inferencia física → anomalía → evidencia → gate de candidatura -- llega a `scientific_candidate_gate=True` cuando corresponde, y que ninguna combinación de evidencia, por fuerte que sea, cambia `identification_state` a nada parecido a "descubierto".

**Lo que esto NO hace todavía, dicho explícitamente:** no parte de píxeles. Los observables (`ratio`, `velocity_kms`, `offset_arcsec`) se dan a mano, como los daría hoy `analyze_pair_core()` tras 899 líneas de extracción de perfiles y ajuste de líneas -- esa parte del pipeline heredado (la más densa científicamente de todo el proyecto: MAPPINGS/3MdB, Rankine-Hugoniot, calibración CCM89) no se ha extraído en esta fase. Intentarlo aquí habría sido precisamente el tipo de extracción apresurada, sin el cuidado que esa lógica merece, que esta reingeniería existe para evitar. Queda como el trabajo concreto de la siguiente fase de extracción (ver sección 3).

## 2. Qué prueba realmente esta fase

No es un ensamblaje cosmético. Las pruebas de integración de esta fase son las primeras de todo el proceso que:

- Escriben un FITS real a disco, lo cargan con el `load_fits` heredado, detectan fuentes reales con DAOStarFinder, las critican con el filtro de artefactos real, las miden con momentos 2D reales, y producen objetos `Candidate` -- sin ningún mock ni simulación de por medio, en una sola prueba.
- Confirman una invariante de conteo real (`n_candidates + n_artifact_rejected == n_detected`), no solo que "no lanza excepción".
- Confirman que la ausencia de WCS se propaga honestamente hasta `IdentificationState.DISCOVERY_REVIEW` en vez de inventar coordenadas o fallar en silencio.
- Confirman que un candidato "especializado" completo (con evidencia física y de anomalía) sigue sin poder representar un estado de "descubierto" -- la garantía central del encargo, verificada contra el modelo de datos real, no contra un documento.

## 3. Verificación

4 tests de integración nuevos. Suite completa tras esta fase:

- Python 3.11.15 sin GUI/red: **100 passed, 3 skipped (GUI + 2 de red), 1 xfailed**.
- Python 3.12.3 con tkinter + Xvfb: **102 passed, 2 skipped (red), 1 xfailed**.

Sin regresiones en ninguno de los 98 tests previos.

## 4. Qué queda

- **Extraer la medición de observables físicos de `analyze_pair_core`** (perfiles Hα/[O III], ajuste de líneas, `GridManager`/`ShockGrid`) para que el modo especializado deje de necesitar una fila dada a mano y pase a partir de píxeles reales, como el modo genérico. Es, con diferencia, la extracción más grande y más delicada científicamente que queda en todo el proyecto -- merece su propia fase dedicada, no un añadido apresurado a esta.
- **Motor Temporal conectado al pipeline**: `temporal.variability`/`measure_proper_motion` existen y están probados (Fase 3, Fase 6) pero `run_generic_discovery` todavía opera sobre una sola `Observation` (una época); conectar series de épocas es trabajo de extender el orquestador, no de un motor nuevo.
- **`DiscoveryStore`/`Project`**: esta fase produce `list[Candidate]` en memoria; persistirlos en un proyecto (`astrophysics_suite.models.project.Project`, ya diseñado en la Fase 4) para que sobrevivan entre sesiones es la base de la Fase 8 (GUI), no de esta.

Con esto, la arquitectura objetivo tiene, por primera vez, una ruta ejecutable de principio a fin que un futuro flujo de GUI (Fase 8) puede invocar directamente -- exactamente el hueco que la Fase 5 (`test_gui_uses_full_pipeline.py`, `xfail` estricto) documentó como pendiente.
