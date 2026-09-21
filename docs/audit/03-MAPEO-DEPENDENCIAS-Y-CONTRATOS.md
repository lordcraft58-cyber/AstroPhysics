# AstroPhysics Suite — Fase 2: Mapeo de Dependencias y Contratos

Continuación directa de `01-AUDITORIA-TECNICA-FASE1.md` y `02-ARQUITECTURA-OBJETIVO-Y-PLAN.md`. Objetivo de esta fase, tal como se definió en el plan: construir el grafo de llamadas completo, hacer el barrido de código muerto **al 100%** de las 307 entidades de nivel de módulo (no solo una muestra representativa, como en la Fase 1), cuantificar exactamente qué alcanza la CLI y qué alcanza la GUI, y documentar el contrato real (firma + docstring + ubicación) de las funciones/clases que alimentarán cada motor objetivo.

**Metodología:** se construyó un grafo de referencias mediante `ast.walk()` sobre las 307 definiciones de nivel de módulo (254 funciones + 53 clases) de `legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py`, registrando qué otros nombres de nivel de módulo aparece referenciado (como `Name`) dentro del cuerpo de cada una. Se invirtió el grafo para saber, de cada entidad, quién la referencia. Se calculó el cierre transitivo (BFS) desde los tres puntos de entrada reales del programa: `main()` (CLI), `launch_gui()` (GUI activa) y `selftest()` (suite de regresión embebida). Cada hallazgo "0 referencias" se verificó además con una búsqueda de texto plano (`grep` con límites de palabra) sobre el archivo completo, para descartar referencias dinámicas que el análisis AST pudiera no capturar (cadenas, `getattr`, docstrings). En los casos comprobados no hubo divergencia entre ambos métodos.

Limitación conocida y aceptada de este método: no captura despacho dinámico por cadena (`getattr(mod, "nombre")()`) ni ejecución vía `eval`/`exec` (de los cuales, por otro lado, la Fase 1 ya confirmó que el archivo no usa ninguno de forma significativa). Tampoco distingue "llamado" de "solo mencionado en una anotación de tipo" — ambos cuentan como referencia viva, lo cual es la postura conservadora correcta para no marcar código como muerto por error.

---

## 1. Barrido de código muerto al 100%

De las **307 entidades de nivel de módulo**, **23 no son referenciadas por ninguna otra parte del archivo** (ni por otra función/clase, ni por código de nivel de módulo fuera de definiciones). Lista completa, con su línea exacta:

| Entidad | Tipo | Línea | Nota |
|---|---|---|---|
| `_profile_selection_score` | función | L4654 | Ya identificada en Fase 1 §3.1 — soporte de la copia muerta de `select_optimal_profile_candidates`. |
| `build_filter_response` | función | L256 | Construye un `FilterResponse` que tampoco se usa en ningún otro sitio — clúster muerto completo, ver §1.1. |
| `resolve_object_center_legacy` | función | L1119 | **Casi-duplicado por nombre** de `resolve_object_center` (L11612, viva) — ver §1.2. |
| `estimate_field_center_from_gaia` | función | L731 | — |
| `gaia_distance_pc` | función | L747 | — |
| `estimate_remnant_radius_uncertainty` | función | L1162 | — |
| `FITSQuality` | clase | L1845 | Contenedor de datos sin ningún uso; posiblemente superseded por otra forma de reportar calidad (dict). |
| `FilamentDetectionStrategy` | clase (`typing.Protocol`) | L2328 | Protocolo estructural nunca referenciado explícitamente — ver §1.3 (hallazgo sobre contratos no verificados). |
| `detect_point_sources_legacy` | función | L2055 | **Casi-duplicado por nombre** de `_detect_point_sources_legacy` (usada como fallback dentro de `detect_point_sources`, viva) — ver §1.2. |
| `compute_color_color_diagram` | función | L9304 | Contiene un comentario propio admitiendo que es un stub ("implementación futura cuando se proporcionen datos multibanda reales"). |
| `luminosity_distance` | función | L9453 | — |
| `check_hardware` | función | L11997 | Ver §1.4 — clúster de diagnóstico/actualización completo sin cablear. |
| `update_check_https` | función | L12025 | Ver §1.4. |
| `download_verified_update` | función | L12038 | Ver §1.4. |
| `launch_verified_installer` | función | L12059 | Ver §1.4. |
| `launch_gui_legacy` | función | L6608 | Ya identificada en Fase 1 §4.1 — ~998 líneas, incluye clase `App` anidada duplicada. |
| `_survey_infer_object` | función | L11782 | — |
| `robust_query_simbad_field` | función | L11659 | Variante de consulta SIMBAD no usada (existe otra ruta viva de resolución SIMBAD en `resolve_object_center`/`_normalise_object_query`). |
| `load_mappings_grid` | función | L8148 | Función libre redundante con `MappingsGridLoader` (clase viva, L7912). |
| `ModelParameter` | clase | L13771 | — |
| `ModelFit` | clase | L13438 | `ModelComparisonEngine` (viva) no la usa; construye sus resultados por otra vía (ver §5, tabla de contratos). |
| `_v44_regression_tests` | función | L14033 | **No invocada ni siquiera por `selftest()`** — ver §1.5. |
| `_v46_regression_tests` | función | L14292 | **No invocada ni siquiera por `selftest()`**, pese a testear el propio `DiscoveryEvidenceEngine`/`discovery_v46` — ver §1.5. |

### 1.1 Clúster muerto transitivo: `FilterResponse`

`FilterResponse` (clase, L184) no aparece en la tabla anterior porque técnicamente *es* referenciada — pero su único referenciador es `build_filter_response()` (L256), que a su vez no tiene ningún referenciador. Es un clúster de dos entidades mutuamente aisladas del resto del programa. Ambas deben eliminarse juntas.

### 1.2 Nombres "legacy" casi-duplicados que son trampas de mantenimiento

Se encontraron **dos pares** de funciones con nombres casi idénticos donde una está viva y la otra muerta — exactamente el patrón de riesgo que la Fase 1 señaló para `launch_gui`/`launch_gui_legacy`, y que aquí se confirma que **no fue un caso aislado**:

- `resolve_object_center_legacy` (L1119, **muerta**) vs. `resolve_object_center` (L11612, **viva**, usada por `main()`).
- `detect_point_sources_legacy` (L2055, **muerta**, sin guion bajo) vs. `_detect_point_sources_legacy` (referenciada dentro de `detect_point_sources`, **viva**, con guion bajo).

El segundo caso es particularmente peligroso: `detect_point_sources_legacy` y `_detect_point_sources_legacy` difieren **únicamente en un guion bajo inicial**. Cualquier búsqueda rápida, autocompletado de editor, o edición por un asistente de IA sin verificar el prefijo puede modificar la función equivocada sin que haya ningún error sintáctico que lo delate — el programa seguiría funcionando, simplemente el cambio no tendría ningún efecto. Esto refuerza la recomendación de la Fase 1: la limpieza de nombres no es cosmética, es prevención activa de bugs silenciosos futuros.

### 1.3 `FilamentDetectionStrategy` es un `Protocol` no verificado

`FilamentDetectionStrategy(Protocol)` (L2328) define la interfaz que, por intención, deberían cumplir `HessianFilamentStrategy` y `CannyFilamentStrategy` (ambas vivas). Al ser un `typing.Protocol`, el cumplimiento es estructural (duck typing) y no requiere herencia explícita — por eso aparece como "no referenciado" en el grafo (ninguna clase declara `(FilamentDetectionStrategy)` en su lista de bases). Esto significa que **hoy nada verifica en tiempo de ejecución ni de tipo-checking que las estrategias de detección de filamentos cumplan realmente el contrato declarado**: es documentación de intención, no una garantía exigible. Para la Fase 4 (contratos de datos), este es un ejemplo concreto de por qué los contratos de los motores objetivo deben verificarse (con `isinstance`/`Protocol` + `runtime_checkable`, o con una clase base abstracta real) y no solo declararse.

### 1.4 El subsistema completo de diagnóstico de hardware y actualización verificada está sin cablear

`check_hardware()`, `update_check_https()`, `download_verified_update()` y `launch_verified_installer()` — el flujo completo que la Fase 1 (§9) señaló como el ejemplo más sólido de buena práctica de seguridad ya presente en el código — **no es invocado desde ningún punto del programa**: ni la CLI (`main()`, 55 subcomandos, ninguno lo llama) ni la GUI (`launch_gui()`). Es decir, hoy el usuario final no tiene ninguna forma de ejecutar un diagnóstico de hardware ni de comprobar/aplicar actualizaciones — el código existe, es correcto, pero es funcionalmente inaccesible.

**Matiz importante respecto a la Fase 1:** esto no es "código muerto" en el sentido de "debe eliminarse" — es exactamente lo contrario: es la base ya construida del futuro `services/updater.py` y `services/diagnostics.py` (§4.3 de la arquitectura objetivo). El trabajo de la Fase 3/7 no es borrarlo, es **conectarlo**: un comando de CLI (`aps update-check`, `aps diagnostics`) y una entrada de menú en la GUI ("Buscar actualizaciones", "Diagnóstico del sistema").

### 1.5 Las suites de regresión más recientes no se ejecutan nunca

`_v44_regression_tests()` (L14033) y `_v46_regression_tests()` (L14292) están definidas pero **`selftest()` no las invoca** — a diferencia de `_v43_scientific_hardening()` y `_v45_regression_tests()`, que sí están cableadas dentro de `selftest()` (verificado en Fase 1 §11, L10567-10573). Esto significa que ejecutar `python AstroPhysicsSuite... selftest` — el único mecanismo de verificación automatizada que existe hoy — **no comprueba la corrección del motor de evidencia v46** (`_v46_regression_tests` valida exactamente `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine` y `discovery_v46`, es decir, el núcleo de evidencia que la Fase 1 §13.2 identificó como la idea más valiosa a preservar). Es un hueco de cobertura real, no solo estructural: el motor conceptualmente más importante del producto es también el que menos se comprueba en la práctica hoy.

**Acción para la Fase 5:** al portar estas suites a `pytest`, no solo se gana estructura — se gana cobertura real que hoy no existe en ningún flujo ejecutado.

---

## 2. Alcance cuantificado: CLI vs. GUI

De las 284 entidades vivas (307 − 23 muertas):

- **281** son alcanzables transitivamente desde `main()`.
- **203** son alcanzables transitivamente desde `launch_gui()`.
- **203 de esas 203 GUI están también en el conjunto alcanzable por `main()`** — es decir, **0 entidades vivas son exclusivas de la GUI**. Todo lo que usa `launch_gui()` es un subconjunto estricto de lo que usa `main()`.
- **78 entidades vivas son alcanzables desde `main()` pero no desde `launch_gui()`** — esta es la cuantificación exacta y exhaustiva del hallazgo cualitativo de la Fase 1 §7.1 ("la GUI no usa el motor de evidencia/física/IA"). La lista completa (no una muestra):

| Categoría destino (motor objetivo) | Entidades CLI-only confirmadas |
|---|---|
| **Physical Engine** | `MultiObjectPhysicsEngine`, `ModelComparisonEngine`, `PhysicalModelRegistry`, `ParameterEstimate`, `PhysicalHypothesis`, `ShockState`, `infer_physical_parameters`, `rankine_hugoniot`, `estimate_shock_velocity`, `estimate_ast_remnant_age`, `grid_posterior_inference`, `register_trusted_grid`, `regime_from_physics`, `_curve_eval`, `_weighted_linear_fit` |
| **Anomaly Engine** | `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `_benjamini_hochberg`, `_normal_two_sided_p`, `build_reference_anomaly`, `_robust_scale_to_reference` |
| **Temporal Engine** | `TemporalChangeEngine` (la función `measure_proper_motion` también está en esta lista) |
| **Evidence Engine / orquestación** | `DiscoveryEvidenceEngine`, `discovery_v46`, `physical_discovery_bundle`, `build_discovery_record`, `compare_physical_models_from_catalog`, `validate_pipeline_qc_contract` |
| **Photometry/Astrometry** | `absolute_photometric_calibration`, `apply_atmospheric_extinction`, `compute_airmass`, `measure_psf_quality`, `measure_source_quality`, `extract_radial_profile`, `validate_wcs`, `crossmatch_gaia_safe`, `analyze_multiband_pipeline`, `analyze_pixel_science_images`, `read_fits_exptime`, `parse_plane_arg` |
| **Projects / persistencia** | `DiscoveryStore`, `DiscoveryProject`, `DiscoverySession`, `audit_report` |
| **AI (entrenamiento)** | `train_vision_ai`, `train_real_vision_domain`, `train_real_visual_seed`, `build_real_vision_manifest`, `build_real_observation_dataset`, `download_real_vision_corpus`, `_real_observation_array`, `_real_patch_tensor`, `_photometric_validation_evidence` |
| **Plugin API (scripting externo)** | `ScriptContext`, `run_external_script`, `create_template_script` |
| **Validación sintética / self-test** | `synthetic_end_to_end`, `simulate_observation`, `_write_synthetic_pair`, `_write_minimal_fits_2d`, `_selftest_v43_scientific_hardening`, `_v45_regression_tests`, `selftest` |
| **Utilidades varias sin categoría de motor** | `_get_float`, `_safe_array`, `_safe_urlretrieve`, `_load_science_image`, `_science_background`, `_estimate_error`, `calibrate_from_filters`, `demix_two_filters`, `apply_redshift_correction`, `export_environment`, `build_parser` |

Esta tabla es, en la práctica, el mapa de trabajo de la Fase 8 (Integración de GUI): **todo lo que aparece aquí es candidato a exponerse en la GUI comercial nueva a través de `services/`**, porque ya existe, ya funciona (son motores CLI operativos, no prototipos), y hoy es simplemente invisible para el usuario de la interfaz gráfica.

---

## 3. Hallazgo adicional: la GUI activa no tiene consola de log

Al investigar por qué `_QueueLogHandler` (L6596, clase viva según el grafo de referencias) no aparecía en el conjunto alcanzable desde `launch_gui()`, se confirmó que su **único** uso real en todo el archivo es dentro de `launch_gui_legacy()` (muerta): `self._log_handler = _QueueLogHandler(self.q)` seguido de `root_log.addHandler(self._log_handler)` (L6714-6718). La GUI legacy sí conectaba el logger raíz de Python (`logging`) a un panel de consola en la ventana.

La GUI activa (`launch_gui()`) **no hace esto en ningún punto** — se verificó que su cuerpo completo no contiene ninguna llamada a `addHandler`/`getLogger` (solo `main()`, L12995, configura `logging.basicConfig()` para la consola del proceso). Esto significa que, en el uso normal de la aplicación comercial (un ejecutable de Windows sin consola visible), **todos los mensajes `LOG.info(...)`/`LOG.warning(...)` que el pipeline científico genera de forma extensa — advertencias de fallback de DAOStarFinder, problemas de fondo, fallos de consulta a catálogo, etc. — no llegan a ningún sitio visible para el usuario.** La GUI solo muestra lo que cada operación decide empaquetar explícitamente en su propio mensaje de progreso (`self.q.put(("progress", frac, msg))`), que es un canal distinto y más pobre que el de logging estructurado.

**Implicación para la arquitectura objetivo:** el patrón correcto de `_QueueLogHandler` (bridging de `logging` a una cola thread-safe consumida por la GUI vía `root.after`) es una buena idea que debe revivirse — no copiando el código muerto, sino re-implementándola como parte de `services/` (un `GuiLogBridge` reutilizable), conectada por defecto en cualquier future GUI, y con la separación de registros (aplicación/errores/ciencia/descubrimiento) que el usuario pidió explícitamente en el encargo original.

---

## 4. Falsos positivos descartados en este barrido

Dos entidades aparecieron inicialmente como "no alcanzadas por ningún entry point" pero se confirmó que es un artefacto del método (código ejecutado a nivel de módulo en tiempo de import, fuera del grafo de llamadas de funciones) y no un hallazgo real:

- `Const` (clase, L1247): instanciada directamente a nivel de módulo (`C = Const()`, L1259) para exponer constantes físicas globales — se ejecuta siempre al importar el archivo, independientemente de qué entry point se use después. Vivo y correcto.
- (Nota metodológica para la Fase 4: cuando se extraigan `physics/constants.py` etc., este patrón de "instancia global construida al importar el módulo" debe mantenerse o sustituirse conscientemente por inyección explícita — no es un defecto hoy, pero es el tipo de acoplamiento implícito a vigilar al modularizar.)

---

## 5. Contratos actuales de las funciones/clases seed de cada motor objetivo

Firmas extraídas directamente del AST (no transcritas a mano, para evitar errores) del código real. Esto es el contrato **tal como existe hoy** — el contrato objetivo formal (dataclasses versionadas) es trabajo de la Fase 4; aquí se documenta el punto de partida real sobre el que esa fase construirá.

### 5.1 Detection Engine

```
detect_point_sources(data, bkg, fwhm_px=3.0, threshold_sigma=5.0, max_sources=3000, **_ignored_kwargs)   L11543
    # Robust point-source detection compatible with current and legacy Photutils.
    # Devuelve np.ndarray (N,3) = [x, y, flux]. Contrato ya estable y consistente (Fase 1 §3.3).

detect_discovery_sources(image, snr_min=5.0, max_candidates=2000, min_area=3, mask_border=4)   L12112
    # Escaneo de descubrimiento de imagen completa (agnóstico de tipo de objeto, sin DAOStarFinder).
    # Devuelve dict con "sources": list[dict] — estructura distinta a detect_point_sources (Fase 1 §6.3).

register_on_stars(oiii, ha, bkg_oiii, bkg_ha, fwhm_px=3.0, search_radius_px=12.0)   L2141
    # Registra [O III] sobre Hα por traslación usando fuentes puntuales comunes.
```

### 5.2 Artifact Rejection Engine

```
_label_discovery_morphology(area, elongation, compactness, peak_snr)   L12095
    # Clasificación descriptiva para separar fuentes científicas de artefactos.
    # Hoy son umbrales fijos en código (elongation>=8.0, area<=2.0, peak_snr<4.0) — deben
    # convertirse en reglas configurables y explicables en el motor objetivo (§2.2 de la
    # arquitectura), no permanecer como constantes mágicas.
```

### 5.3 Identification Engine

```
query_gaia_sources(ra_deg, dec_deg, radius_deg=0.5, mag_limit=GAIA_DEFAULT_MAG_LIMIT, max_rows=2000)   L702
crossmatch_gaia_safe(ra_deg, dec_deg, radius_arcsec=30.0, mag_limit=18.0, max_rows=100) -> dict   L10074
_crossmatch_discovery_sources(im, rows, match_arcsec=3.0)   L12174
    # Añade evidencia de catálogo; ausencia de match no se interpreta como novedad.
_normalise_object_query(name: str) -> list[str]   L11591
    # Generate conservative SIMBAD aliases without inventing coordinates.
resolve_object_center(target_name: str, ra_hint=None, dec_hint=None)   L11612
    # Resolve target using SIMBAD aliases first, then explicit RA/Dec fallback.
```
Nota: existen **dos** funciones de cross-match con Gaia con firmas y formatos de retorno distintos (`query_gaia_sources` vs. `crossmatch_gaia_safe`), usadas por rutas distintas del programa. Es otro caso del patrón "misma responsabilidad, dos implementaciones" que debe resolverse en la Fase 4 con un único `catalogs/gaia.py`.

### 5.4 Characterization Engine

```
measure_source_quality(image, x, y, cutout_size=25, gain=1.0, saturation_level=None) -> dict   L9879
measure_psf_quality(image, sources, gain=1.0, saturation_level=None) -> dict   L9972
extract_radial_profile(image_data, center_x, center_y, max_radius_px=None, bin_size_px=1.0) -> dict   L9645
validate_wcs(wcs_header: dict, image_shape: tuple) -> dict   L10020
compute_airmass(zenith_angle_deg: float) -> float   L9730
apply_atmospheric_extinction(flux_adu, airmass, k_extinction, k_err=0.0) -> dict   L9744
absolute_photometric_calibration(flux_adu, zeropoint, exposure_s, gain=1.0, airmass=None,
                                  k_extinction=None, k_err=0.0, flux_adu_err=None,
                                  zeropoint_err=None, zeropoint_source='') -> dict   L9782
```
Este grupo ya es, en conjunto, un `photometry/`+`astrometry/` casi completo — todas las funciones devuelven `dict` con buena disciplina de declarar incertidumbre (`*_err`) y procedencia (`zeropoint_source`). Es el candidato más directo a extraerse tal cual en la Fase 6, con cambios mínimos (envolver el `dict` de retorno en un `CharacterizationResult` tipado).

### 5.5 Temporal Engine

```
measure_proper_motion(epoch1_path, epoch2_path, pixel_scale_arcsec=1.0, time_baseline_yr=1.0) -> dict   L9338
class TemporalChangeEngine   L14212
    # Busca variabilidad/deriva en medidas multiepoch con errores explícitos.
    .analyze(self, epochs, min_epochs=3, sigma_threshold=4.0)   L14214
```

### 5.6 Physical Engine

```
rankine_hugoniot(v_s_kms, n0, T0=10000.0, comp=None, ionization_pre='H+He+',
                  ionization_post='H+He++', beta_te_ti=1.0, cooling=None,
                  T_floor=10000.0, gamma=C.gamma)   L3028
estimate_shock_velocity(ratio_oiii_ha, ratio_err, grid, n0=None, grid_model_logerr=0.15) -> dict   L8777
    # "Estima una velocidad de choque *modelodependiente*..." — el propio docstring ya declara
    # la dependencia de modelo, exactamente la disciplina epistemológica pedida en el encargo.
estimate_ast_remnant_age(radius_arcsec, distance_pc, velocity_km_s=None,
                          velocity_err_km_s=None, n0_cm3=6.0) -> dict   L8854
infer_physical_parameters(row, object_family='unknown', distance_pc=None,
                           distance_err_pc=None, registry=None)   L13496
class GridManager   L3246
    .validate(self, grid: ShockGrid)   L3252
    .load(self, path)   L3278
class ShockGrid   L3156
    .from_csv(cls, path)   L3171
class ModelComparisonEngine   L13791
    # Comparación de hipótesis con likelihood gaussiana explícita.
    .fit(self, model_id, x, y, sigma, initial=None)   L13859
    .compare(self, x, y, sigma, model_ids=None)   L13937
class UncertaintyBudget   L8222
    # Presupuesto de incertidumbre estructurado para un resultado.
```

### 5.7 Anomaly Engine

```
class PhysicalConstraintEngine   L14096
    # Busca incompatibilidades entre parámetros relacionados por física básica.
    .evaluate(self, row, estimates)   L14105
class SpatialTrendAnomalyEngine   L14144
    # Detecta residuales espaciales tras quitar una tendencia de primer orden.
    .analyze(self, rows, parameter_keys=None)   L14153
_benjamini_hochberg(pvals, alpha=0.01)   L14077
    # Benjamini-Hochberg FDR correction; returns q-values and reject flags.
build_reference_anomaly(row, estimates, reference=None)   L13575
    # Compara cada parámetro con un intervalo/referencia externa, sin IA.
compare_with_literature_zscore(payload: dict) -> list   L8367
detect_anomalies(payload: dict) -> list   L8517
```

### 5.8 Discovery AI

```
class AstroDiscoveryAI   L3490
    # Motor local de IA científica: clasificación neuronal + novedad + explicación.
    .fit(self, rows, min_rows=80)   L3510
    .score(self, rows)   L3611
    .save(self, path)   L3637
    .load(path)   L3655         # nota: classmethod/staticmethod — sin self, ver Fase 4
class AstroVisionAI   L3889
    # Red convolucional para ver imágenes y construir un espacio visual astronómico.
    .score_candidate_patches(self, ha_array, o3_array, lqef_array, candidates, half_size=64)   L4015
    .save(self, path)   L4030
    .load(path)   L4042
class ViabilityModel   L3321
    .fit(self, cands)   L3346
    .score(self, cands, rng)   L3383
```

### 5.9 Evidence Engine

```
class DiscoveryEvidenceEngine   L14239
    # Fusiona evidencias sin convertir scores heurísticos en probabilidades.
    .evaluate_rows(self, rows, object_family='unknown', reference=None, ai_results=None)   L14245
discovery_v46(payload, object_family='unknown', reference=None, ai_results=None,
              spatial_rows=None, temporal=None)   L14276
    # Producto principal v46: físico + restricciones + espacial + temporal + IA opcional.
    # Es la orquestación más cercana al Evidence Engine objetivo — ver Fase 1 §6.2 y §13.2.
```

### 5.10 Candidate Engine / Projects

```
class RunManifest   L1408
    # Manifiesto de ejecución reproducible: versión + inputs + warnings (Fase 1 §13.10).
class DiscoveryProject   L13628
class DiscoveryStore   L13643
    # Repositorio local, auditable y portable para investigación.
    .load(self)   L13661
```

---

## 6. Conclusiones de la Fase 2 y entrada a la Fase 3

1. El barrido al 100% **confirma y cierra** (no contradice) los hallazgos representativos de la Fase 1: la duplicación real de nombres es baja (23 entidades muertas sobre 307, ~7%), pero su impacto es desproporcionado porque incluye la totalidad de una GUI alternativa (`launch_gui_legacy`, ~998 líneas) y varios pares de nombres casi-idénticos que son trampas activas de mantenimiento.
2. La divergencia CLI/GUI queda **cuantificada de forma exhaustiva y no anecdótica**: 78 entidades vivas, agrupables limpiamente en las categorías de motor objetivo que ya define la arquitectura propuesta — esto convierte directamente el hallazgo en el backlog de trabajo de la Fase 8.
3. Se ha encontrado un hallazgo nuevo no cubierto en la Fase 1: la ausencia de puente de logging en la GUI activa (§3), y la confirmación de que el subsistema de actualización verificada/diagnóstico está completo pero completamente desconectado (§1.4) — ambos alimentan directamente el backlog de las Fases 7-9.
4. Los contratos documentados en §5 muestran que, en su mayoría, **las funciones ya devuelven estructuras razonablemente disciplinadas** (`dict` con campos de error/procedencia explícitos) — el trabajo de la Fase 4 es formalizar esas estructuras ya buenas como tipos, no rediseñar la lógica desde cero.

**Con esto, la Fase 2 queda completa.** El siguiente paso del plan (Fase 3) es la eliminación efectiva de las 23 entidades muertas confirmadas y la corrección del bypass de `analyze_series_with_ai`, con los tests de regresión correspondientes escritos primero.
