# AstroPhysics Suite — Fase 6 (continuación): Los Siete Motores Restantes

Continuación de `07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md` (que cubrió `io/` y `detection/`). Este documento cubre los siete motores restantes de la lista que ese documento dejó pendiente: Artifact Rejection, Identification, Characterization, Physical, Anomaly, Temporal y Evidence. Mismo patrón en los siete: delegar el algoritmo heredado ya probado, traducir a los contratos tipados de la Fase 4, verificar con datos reales (no mocks), documentar honestamente lo que queda fuera de alcance.

**Hallazgo científico real descubierto al escribir estos tests** (sección 7): las dos comprobaciones de consistencia interna de `PhysicalConstraintEngine` (edad Sedov vs. radio/velocidad; temperatura de choque fuerte vs. velocidad) son **inalcanzables en la práctica** cuando se invocan a través de la ruta de producción real (`DiscoveryEvidenceEngine.evaluate_rows`, usada también por `discovery_v46()`/`physical_discovery_bundle()`). No es un hallazgo teórico: se detectó porque un test escrito para confirmarlas falló, y la investigación reveló la causa exacta.

## 1. Artifact Rejection (`artifacts/morphology_screen.py`)

Envuelve `legacy..._label_discovery_morphology()`. Separa deliberadamente dos preguntas que la función heredada respondía en un único `(state, reason)`: ¿es esto un artefacto? (`artifact_checks_for` → `ArtifactCheck`) y ¿qué tan limitada es la calidad? (`quality_check_for` → `QualityCheckItem`). El estado heredado `QUALITY_LIMITED` no es ni un artefacto confirmado ni una fuente limpia -- conflar ambas preguntas es el mismo patrón de vocabulario mezclado que la Fase 4 existe para resolver.

**Límite honesto:** la función heredada solo distingue elongación/compacidad/S-N extremos. NO clasifica entre las 13 categorías de `ArtifactKind` (hot pixel, rayo cósmico, reflejo, gradiente, donut, residuo de stacking, traza de satélite...) porque no existe lógica real para la mayoría de ellas en el código heredado. Inventar esa clasificación sin base científica validada habría violado el principio central de esta reingeniería. 5 tests, cubren los cuatro estados posibles.

## 2. Identification (`catalogs/gaia.py`)

Unifica en un único cliente lo que antes eran dos implementaciones de cross-match Gaia con formatos de retorno distintos (`query_gaia_sources` y `crossmatch_gaia_safe`, Fase 4 §7 nota 3) -- este paquete usa solo `crossmatch_gaia_safe` (la más autocontenida, ya captura toda excepción de red).

Se separó deliberadamente en dos capas: `classify_against_gaia_neighbors()` (función **pura**, sin red, decide `IdentificationState` a partir de una lista de filas Gaia ya obtenida) y `query_gaia_neighbors()`/`identify_detection()` (la orquestación con red real). Esta separación no es capricho arquitectónico: **el host de Gaia (`gea.esac.esa.int`) no está en la lista de permitidos del proxy de red de este entorno de desarrollo** (verificado: `astroquery.gaia` devuelve `HTTPError 403: Host not in allowlist`), así que sin esta separación no habría sido posible probar nada de este motor sin red. La lógica de clasificación (5 tests, incluye desempate por distancia más cercana) se prueba exhaustivamente sin red; la consulta real (`test_gaia_network.py`) se salta explícitamente si la consulta falla, no si falla un precheck de socket TCP -- se comprobó empíricamente que el proxy acepta la conexión TCP y solo rechaza a nivel HTTP, así que un precheck por socket habría dado un falso "disponible".

## 3. Characterization (`photometry/quality.py`)

Envuelve `legacy...measure_source_quality()`. **Hallazgo de diseño, no de bug:** esta función y `enrich_star_rows()` (usada en `detection/point_sources.py`) calculan FWHM/elipticidad con fórmulas de momentos de segundo orden ligeramente distintas, para dos etapas de pipeline diferentes -- el mismo patrón de "misma medición, dos implementaciones independientes" que motivó toda esta reingeniería (Fase 1, sección central). No se unificaron en este slice (unificarlas es un cambio de comportamiento numérico que merece su propio análisis, no una decisión de paso), pero queda documentado explícitamente en vez de repetirse sin comentario.

Mismo patrón de conversión de convención de forma que en `detection/`. Cuando `measure_source_quality` devuelve `state != "OBSERVABLE"` (p. ej. recorte demasiado pequeño), el resultado no se descarta ni se rellena con ceros: se devuelve un `CharacterizationResult` con los campos numéricos en `None` y un `Quantity.not_available(...)` explicando por qué, en `extra["quality_measurement"]`.

**Límite honesto:** no cubre calibración fotométrica absoluta (`absolute_photometric_calibration`, necesita zeropoint/exposición/ganancia que `Observation` no carga hoy) ni perfiles radiales (`extract_radial_profile`, necesita un centro definido de fuente extendida, un caso distinto al punto-fuente de este slice).

## 4. Physical (`physics/inference.py`)

Envuelve `legacy...infer_physical_parameters()`, que ya distingue OBSERVADO/CALIBRADO/INFERIDO por parámetro. Opera sobre un `row: dict` (el mismo contrato que la función heredada), **no** sobre `CharacterizationResult` -- los observables que necesita (`ratio`, `offset_arcsec`, `velocity_kms`, `radius_pc`) son específicos del pipeline de choque OIII/Hα (`analyze_pair_core`), que todavía no se ha extraído. Forzar un adaptador `CharacterizationResult → row` genérico antes de extraer ese pipeline habría producido un adaptador casi siempre vacío -- deuda técnica disfrazada de progreso.

**Nota de diseño importante:** una sola llamada puede producir varios parámetros, cada uno potencialmente de un modelo físico distinto (`physical_scale_distance` para el tamaño, `sedov_uniform_medium` para la edad, simultáneamente). `PhysicalInference` tiene un único `model_id`/`model_hypotheses` a nivel de inferencia -- la procedencia real, por parámetro, se guarda en `Quantity.method`/`Quantity.notes` de cada parámetro individual (que sí es granular); los campos a nivel de `PhysicalInference` quedan como resumen (unión de modelos/hipótesis realmente usados). Test explícito (`test_infer_physical_inference_never_derives_velocity_without_model`) que fija, como regresión permanente, que un ratio sin velocidad medida nunca produce una velocidad -- exactamente la sobre-inferencia que el encargo original prohíbe.

## 5. Anomaly (`anomaly/physical_tension.py`)

Cubre la dimensión `physical` de `AnomalyVector` combinando `legacy...PhysicalConstraintEngine` (tensión interna) y `legacy...build_reference_anomaly` (comparación externa) en una única `Quantity` resumen (el mayor \|z-score\| entre ambas fuentes), con el desglose completo en `notes` -- nunca un booleano sin explicación.

**Límite honesto:** no cubre las otras seis dimensiones. `spatial` requiere `SpatialTrendAnomalyEngine` operando sobre una *población* de detecciones a la vez (forma de entrada distinta al resto de este documento, que opera detección-a-detección); `photometric`/`morphological`/`spectral`/`temporal`/`astrometric` no tienen todavía una fuente de datos poblada por los motores ya extraídos.

## 6. Temporal (`temporal/variability.py`)

Envuelve `legacy...TemporalChangeEngine` (chi² constante vs. ajuste lineal ponderado sobre medidas multiépoca con error explícito). No cubre movimiento propio (`measure_proper_motion`, ya con regresión propia desde la Fase 3) ni aparición/desaparición (requieren comparar presencia/ausencia de detecciones entre épocas, un problema distinto a una serie de valores continua).

## 7. Evidence (`evidence/fusion.py`) — y el hallazgo del `PhysicalConstraintEngine` inalcanzable

Envuelve `legacy...DiscoveryEvidenceEngine.evaluate_rows()`, que ya implementa el principio correcto de independencia de evidencias. Traduce sus cuatro señales internas (tensión física, anomalía de referencia, discrepancia de modelo, novedad visual) a `EvidenceItem` explícitos por motor de origen -- y `EvidenceChain.independent_evidence_count` (propiedad calculada de la Fase 4, no un campo que se pueda falsear) reproduce exactamente el mismo conteo que el motor heredado ya calculaba. Esto confirma que el diseño de la Fase 4 generaliza correctamente la idea original, no solo la reetiqueta.

**El hallazgo:** al escribir un test para confirmar que una tensión física interna (p. ej. edad Sedov inconsistente con radio/velocidad) aparecía como `EvidenceItem`, el test fallaba sistemáticamente. La investigación (reproducida de forma aislada, no solo inferida leyendo código) confirmó la causa:

```
>>> row = {"radius_pc": 1.0, "velocity_kms": 100.0}
>>> inf = infer_physical_parameters(row, object_family="SNR")
>>> list(inf["parameters"].keys())
['postshock_temperature_K', 'age_yr']
```

`infer_physical_parameters()` **nunca copia `radius_pc` ni `velocity_kms` a su propio diccionario de salida** -- solo sus magnitudes derivadas. `PhysicalConstraintEngine.evaluate(row, estimates)` lee `radius_pc`/`velocity_kms`/`age_yr` de `estimates` (el segundo argumento), no de `row`. Cuando `DiscoveryEvidenceEngine.evaluate_rows()` construye `estimates` llamando a `infer_physical_parameters(row, ...)` -- la ruta de producción real, la que usan también `discovery_v46()` y `physical_discovery_bundle()` -- `estimates` nunca contiene `radius_pc`/`velocity_kms`, así que **ambas comprobaciones de consistencia interna de `PhysicalConstraintEngine` están, en la práctica, permanentemente inactivas** en todo el pipeline de producción actual. No por falta de tensión en los datos reales: la comprobación ni siquiera llega a ejecutarse, porque sus variables de entrada son siempre `NaN` por este desajuste de contrato.

Esto es, además, motivo de sospecha razonable sobre `_v46_regression_tests()` (la suite embebida conectada a `selftest()` en la Fase 3): su aserción `assert c["n_physical_tensions"]==0` para un caso "consistente" pasa trivialmente si la comprobación nunca se ejecuta, no necesariamente porque la física sea correcta. No se ha modificado esa suite en esta fase -- señalar el problema con evidencia reproducible es el alcance correcto aquí; decidir cómo corregirlo (¿hacer que `infer_physical_parameters` incluya los observables crudos en su salida? ¿pasar `row` directamente donde hoy se pasa `estimates`?) es una decisión de diseño científico que le corresponde a quien tenga autoridad sobre la física del proyecto, no a una extracción de arquitectura.

`astrophysics_suite/anomaly/physical_tension.py` (§5) **no sufre este problema**: acepta `parameters: dict[str, Quantity]` como argumento independiente en vez de derivarlo automáticamente de `row`, así que un llamador que sí disponga de `radius_pc`/`velocity_kms` medidos (o los añada explícitamente) puede ejercer la comprobación correctamente -- verificado en `test_flags_tension_when_age_is_wildly_inconsistent`, que documenta la distinción en su propio docstring para que nadie la pierda de vista.

## 8. Verificación

29 tests nuevos (7 motores). Suite completa tras esta fase:

- Python 3.11.15 sin GUI/red: **96 passed, 3 skipped (GUI + 2 de red), 1 xfailed**.
- Python 3.12.3 con tkinter + Xvfb: **98 passed, 2 skipped (red), 1 xfailed**.

Sin regresiones en ninguno de los 69 tests previos (Fases 3-6 slice 1).

## 9. Estado de `astrophysics_suite/` tras esta fase

```
astrophysics_suite/
├── core/          # ValueKind, IdentificationState, ReviewState, ArtifactKind, MorphologyClass, QualityLevel, Quantity, Provenance
├── models/        # los 8 contratos de la Fase 4 + legacy_adapter
├── io/            # carga real de FITS -> Observation/ImageRef
├── detection/      # detección real de fuentes puntuales -> Detection
├── artifacts/      # filtro morfológico -> ArtifactCheck/QualityCheckItem
├── catalogs/       # identificación Gaia -> IdentificationState/CatalogMatch
├── photometry/     # calidad por fuente -> CharacterizationResult
├── physics/        # inferencia física por fila -> PhysicalInference
├── anomaly/        # tensión física -> AnomalyVector.physical
├── temporal/       # variabilidad multiépoca -> TemporalEvidence
└── evidence/       # fusión de evidencia -> EvidenceChain
```

Los nueve motores conceptuales del encargo original tienen ahora un primer corte real, probado, en su paquete correspondiente. Ninguno reimplementa el algoritmo heredado desde cero; todos lo delegan y lo tipan. Lo que queda -- generalizar estos cortes a los otros dos pipelines de descubrimiento (el de choque OIII/Hα completo y el motor v46), y fusionarlos en una única ruta `Observation → Candidate` -- es exactamente el trabajo que la Fase 7 tiene reservado (Fase 1, sección 6).
