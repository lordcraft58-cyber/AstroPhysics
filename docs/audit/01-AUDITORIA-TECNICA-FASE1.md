# AstroPhysics Suite — Auditoría Técnica Completa (Fase 1)

**Objeto auditado:** `legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py`
**Versión interna declarada:** `__version__ = "57.0.0"` (línea 113), `SCHEMA_VERSION = 39` (línea 114)
**Tamaño:** 14.312 líneas, 775.295 bytes, un único módulo Python
**Metodología:** parseo AST completo (Python 3.12), inventario exhaustivo de clases/funciones/métodos en todos los ámbitos (módulo, anidado, métodos), búsqueda dirigida de los defectos ya reportados por el usuario, lectura íntegra de las rutas de ejecución críticas (CLI `main()`, `launch_gui()`, `analyze_pair_core()`, motores de descubrimiento), y verificación cruzada de cada hallazgo contra el código real (número de línea exacto) antes de incluirlo aquí. No se ha asumido nada que no se haya podido verificar leyendo el código.

Este documento es la **Fase 1** solicitada: auditoría, no reescritura. Todos los hallazgos incluyen ubicación exacta para que sean verificables y accionables.

---

## 0. Veredicto ejecutivo

El proyecto **no es un mal código científico** — es, de hecho, notablemente más riguroso y más consciente de seguridad de lo que cabría esperar de un archivo de 14K líneas crecido orgánicamente durante ~30 iteraciones (`v27` → `v57`, a juzgar por las cabeceras de sección). Existen ideas científicas y de ingeniería que merecen conservarse explícitamente (sección 13). El problema **no es la ciencia; es la arquitectura**: el archivo ha acumulado **tres pipelines de "descubrimiento" independientes y no interoperables**, una GUI activa que solo usa una fracción mínima de los motores científicos existentes, código muerto significativo, y al menos un defecto que impide que el programa arranque en la mayoría de instalaciones de Python actuales. Esto confirma exactamente la hipótesis de partida del usuario: se necesita reingeniería de arquitectura, no una lista de parches.

**Hallazgo más grave (P0, bloqueante):** el archivo no es sintácticamente válido en Python 3.10/3.11 — solo en 3.12+. Ver §1.

---

## 1. P0 — El archivo no arranca en Python ≤3.11

```
python3.11 -c "import ast; ast.parse(open('AstroPhysicsSuite_v57_3_COMMERCIAL.py').read())"
→ SyntaxError: f-string expression part cannot include a backslash (línea 5733)
```

Línea 5733, dentro de `write_html_report()` (L5719-5816):

```python
body.append(f"<p><b>Estado:</b> {'<span class=\"ok\">PASS</span>' if sc.get('passed') else '<span class=\"warn\">FAIL</span>'}</p>")
```

La gramática de f-strings relajada (comillas escapadas dentro de la expresión) es **PEP 701, introducida en Python 3.12** (octubre 2023). En Python 3.10/3.11 —todavía extremadamente comunes, y una elección habitual para builds de PyInstaller por madurez de wheels de NumPy/PyTorch/Astropy— **el módulo entero falla en `import`, antes de ejecutar una sola línea**. No es un bug de una función: es un fallo de carga del programa completo.

**Impacto:** cualquier build comercial para Windows hecha con un intérprete <3.12 no arranca. Cualquier usuario que ejecute el script con su Python del sistema (si no es 3.12+) no puede ni ver el mensaje de error de la aplicación.

**Causa raíz:** el archivo se ha ido escribiendo asumiendo un intérprete de desarrollo moderno (probablemente 3.12/3.13, ver entorno de este contenedor) sin fijar ni verificar nunca la versión mínima objetivo de despliegue.

**Acción recomendada para la Fase objetivo:** (a) fijar una versión mínima soportada explícita (recomendación: 3.11, por compatibilidad de wheels científicos en Windows) y (b) añadir un test de CI que haga `ast.parse()` del código con la versión mínima objetivo, no con la versión de desarrollo. Este es exactamente el tipo de regresión silenciosa que debe ser estructuralmente imposible en la arquitectura nueva.

---

## 2. Mapa real del código actual

El propio archivo documenta su historia mediante cabeceras de sección (`# ====`) que referencian versiones desde `v27` hasta `v57`. Reconstruyendo la cronología por orden de aparición en el archivo (que **no** coincide con el orden de versión, señal directa de acreción desordenada):

| Rango de líneas | Sección (tal como aparece en el código) | Versión referenciada |
|---|---|---|
| 122–493 | Filtros permitidos, grilla embebida, RAM/workers | — |
| 695–1243 | Gaia, caracterización estelar, resolución de centro/radio | — |
| 1560–2392 | FITS I/O, fondo, registro, detección DAOStarFinder, crestas | — |
| 2451–3419 | Perfiles estelares, ajuste, calibración, física, grillas ML | — |
| 3419–4065 | AstroDiscoveryAI | **v33** |
| 3815–4065 | AstroVisionAI | **v34** |
| 4065–4332 | Motor físico multiobjeto | **v35** |
| 4230–4332 | Motor de anomalías físicas multiparámetro | **v36** |
| 4582–4698 | Configuración/selección de perfiles según objeto | **v30** |
| 4698–5868 | **Pipeline principal** (`analyze_pair_core`) | — |
| 6593–7607 | GUI **legacy** (código muerto, ver §4.1) | — |
| 7608–7894 | Contrato de esquema científico / consistencia | **SECTION 49** |
| 7894–8218 | Cargador/validador de grids MAPPINGS/3MdB | **SECTION 37** |
| 8218–8935 | Presupuesto de incertidumbre, comparación literatura, anomalías, QC, forward modeling, velocidad de choque, edad | **SECTIONS 40,44,42,46,38,39,36** |
| 8935–9417 | Motor de imagen a nivel de píxel, stacker multibanda, movimiento propio | **v51, SECTION 34, 35** |
| 9417–10476 | Redshift, provenance, mapas 2D, perfiles radiales, calibración fotométrica absoluta, PSF/seeing, WCS+Gaia, calibración espectrofotométrica de color, conexión multibanda | **SECTIONS 41,50,28,27,45; v29; v30** |
| 10476–11184 | Selftest embebido | — |
| 11184–11374 | Sistema de scripts externos (Plugin API v1.0) | — |
| 11374–11516 | CLI (`build_parser`) | — |
| 11516–12076 | "GUI simplificada" (en realidad: reescritura de utilidades núcleo — `detect_point_sources`, etc., ver §4.2) | **v52** |
| 12076–12317 | **Discovery Workspace** (tercer pipeline de descubrimiento, ver §6) | **v57** |
| 12317–12991 | `launch_gui()` — **GUI activa real** | — |
| 12993–13344 | `main()` — despachador CLI (55 subcomandos) | — |
| 13344–13407 | Dataset de observación real + preentrenamiento de dominio | **v47** |
| 13407–13761 | Motor de inferencia física y descubrimiento multiparámetro | **v40, v41** |
| 13761–14038 | Motor de competición de modelos físicos (AICc/BIC) | **v42** |
| 14038–14312 | Motores de alta gama: restricciones físicas, anomalías espaciales, cambios temporales, fusión de evidencia | **v46** |

**Lectura arquitectónica de esta tabla:** las secciones **no están organizadas por capa** (detección / identificación / física / IA / GUI), sino por **orden cronológico de aparición de la idea**. El motor de anomalías espaciales y el motor de fusión de evidencia (que conceptualmente deberían ejecutarse *después* del motor físico de v40/v41) están físicamente *después* en el archivo pero fueron escritos *después* en el tiempo, no por dependencia lógica. Esto es la firma clásica de un monolito que ha crecido por "añadir al final", no por diseño de capas.

### 2.1 Inventario cuantitativo

- **53 clases** de nivel de módulo, 33 con métodos (105 métodos en total).
- **255 funciones** de nivel de módulo.
- **468 definiciones de función** en total (módulo + anidadas + métodos).
- **55 subcomandos de CLI** (`argparse`, un único `main()` con 55 bloques `if args.cmd==...`).
- **14 dependencias opcionales** con detección en tiempo de import (`HAS_ASTROPY`, `HAS_CANNY`, `HAS_GAIA`, `HAS_MPL`, `HAS_OPENPYXL`, `HAS_PANDAS`, `HAS_PHOTUTILS[...]`, `HAS_SIMBAD`, `HAS_SKIMAGE`, `HAS_SKLEARN`, `HAS_SPARSE`, `HAS_TORCH`).
- **0 archivos de test**, **0 `requirements.txt`/`pyproject.toml`/`setup.py`**, **0 spec de PyInstaller** en el repositorio (el repositorio, de hecho, estaba vacío salvo un `README.md` antes de esta auditoría).

### 2.2 Clasificación de las 53 clases (para orientar la futura estructura de paquetes)

| Categoría | Clases | Destino conceptual futuro |
|---|---|---|
| Filtros / transmisión | `FilterTransmission`, `FilterResponse` | `io`/`photometry` |
| Constantes / composición química | `Const`, `Composition` | `physics` |
| Manifiesto de ejecución / reproducibilidad | `RunManifest` | `core`/`provenance` |
| Imagen FITS | `FitsImage`, `AmbiguousCubeError`, `Background`, `FITSQuality` | `io` |
| Registro | `Registration` | `astrometry` |
| Detección de estructuras | `RidgeMap`, `FilamentDetectionStrategy`, `FilamentDetectionResult`, `HessianFilamentStrategy`, `CannyFilamentStrategy` | `detection` |
| Perfiles y ajuste | `Profile`, `SamplingOperator`, `PeakFit` | `photometry` |
| Calibración / líneas | `LineCalibration`, `LineRatio`, `FluxMeasurement` | `photometry`/`spectroscopy` |
| Física de choques | `CoolingCurve`, `ShockState`, `GridSolution`, `ShockGrid`, `GridManager` | `physics` |
| ML clásico | `ViabilityModel`, `_PersistedMedianImputer` | `ai` |
| IA de descubrimiento/visión | `AstroDiscoveryAI`, `DiscoverySession`, `_AstroConvAutoencoder`, `AstroVisionAI` | `ai` |
| Física multiobjeto | `MultiObjectPhysicsEngine` | `physics` |
| Parámetros de análisis | `AnalysisParams`, `AnalysisCancelled` | `core`/`models` |
| GUI (muerta) | `_QueueLogHandler` (viva), `App` anidada en `launch_gui_legacy` (muerta) | `gui` / eliminar |
| Contratos científicos | `ScientificConsistencyReport` | `evidence` |
| MAPPINGS/3MdB | `MappingsGridMetadata`, `MappingsGridLoader` | `physics` |
| Incertidumbre | `UncertaintyBudget` | `physics` |
| Scripting externo | `ScriptContext` | `services`/plugin API |
| Modelos físicos / comparación | `ParameterEstimate`, `ModelFit`, `PhysicalModelRegistry`, `ModelParameter`, `PhysicalHypothesis`, `ModelComparisonEngine` | `physics` |
| Proyecto / almacenamiento | `DiscoveryProject`, `DiscoveryStore` | `projects` |
| Motores de anomalía/evidencia (v46) | `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine`, `DiscoveryEvidenceEngine` | `anomaly`, `temporal`, `evidence` |

Esta tabla confirma que **el material conceptual para casi todos los motores que pide el usuario ya existe** en alguna forma. El trabajo de la Fase objetivo no es "inventar" los motores desde cero, sino **extraerlos, darles un contrato único y conectarlos**, cosa que hoy no ocurre (ver §6).

---

## 3. Duplicados reales vs. falsos positivos

Se comprobó **todo** el árbol AST (no solo el nivel de módulo) en busca de nombres repetidos, incluyendo funciones anidadas dentro de condicionales o closures.

### 3.1 Duplicado real confirmado: `select_optimal_profile_candidates`

Existen **dos implementaciones completas** al nivel de módulo:

- **L4674–4695** (versión antigua): usa `_profile_selection_score()` (L4654), selección por top-N simple según score.
- **L11721–11756** (versión nueva): usa `_profile_selection_quality()` (L11697, score logarítmico con más componentes — ratio, chi², forma, distancia a estrella) **más** un algoritmo goloso de diversidad espacial (evita agrupar candidatos muy próximos), y marca explícitamente `c["status"]="ok"`.

En Python, la segunda definición de módulo **sobrescribe** la primera de forma silenciosa: cualquier llamada a `select_optimal_profile_candidates(...)` en cualquier punto del programa resuelve siempre a la implementación de L11721. **La primera (L4674) es código muerto**, pero además es una trampa de mantenimiento: si alguien "arregla un bug" en la lógica de selección de perfiles y edita por error la copia de L4674, el cambio no tendrá ningún efecto observable — un patrón de bug silencioso clásico. `_profile_selection_score()` (L4654), usada únicamente por la versión muerta, es igualmente código muerto.

**Veredicto:** conservar la lógica de L11721 (más sofisticada, con diversidad espacial — buena idea científica: evita que "N candidatos" sean en realidad la misma estructura sobre-muestreada). Eliminar L4654–4695 en su totalidad tras confirmar que ningún caller externo (scripts de plugin, notebooks del usuario) depende de la firma antigua.

### 3.2 Falsos positivos de duplicación (verificados y descartados)

El usuario pidió explícitamente no asumir que los ejemplos dados eran los únicos problemas, así que se hizo una búsqueda exhaustiva de *todos* los nombres repetidos en cualquier ámbito. Resultado, con veredicto de cada uno:

| Nombre repetido | Ocurrencias | Veredicto |
|---|---|---|
| `__init__` | 20 | **Normal.** Son constructores de 20 clases distintas — no es duplicación, es OOP. |
| `worker` | 8 | **Normal.** Closures locales dentro de distintos manejadores de botón en `launch_gui`/`launch_gui_legacy`; cada uno tiene su propio ámbito. No hay colisión real. |
| `load` / `save` / `fit` / `score` / `analyze` / `to_dict` / `from_csv` / `detect` | 2–5 c/u | **Normal.** Métodos de igual nombre en clases distintas (`GridManager.load` ≠ `AstroDiscoveryAI.load` ≠ `MappingsGridLoader.load`), patrón polimórfico esperado. |
| `select_optimal_profile_candidates` | 2 | **Real**, ver §3.1. |

Esto es relevante porque confirma que la duplicación real en este archivo **no es masiva** a nivel de nombres de función — el problema dominante no son "funciones idénticas copiadas", sino **pipelines completos reimplementados en paralelo con nombres distintos** (§6), que es un problema más difícil de ver con un grep simple y es precisamente el tipo de hallazgo que esta auditoría manual estaba buscando.

### 3.3 Los defectos históricos citados por el usuario: estado real verificado

| Defecto reportado | Estado verificado en v57.0.0 |
|---|---|
| Múltiples `launch_gui()` | **Parcialmente cierto, y peor de lo que sugiere el nombre.** Existe `launch_gui()` (L12317, activa, invocada desde `main()` L13157) y `launch_gui_legacy()` (L6608, **código muerto**, cero llamadas en todo el archivo). `launch_gui_legacy` contiene una clase `App` anidada de facto duplicada (~1000 líneas) que ya nadie usa. Ver §4.1. |
| Duplicación de `detect_point_sources()` | **No confirmado como duplicado hoy.** Solo existe una definición (L11543), con fallback interno a `_detect_point_sources_legacy()` para versiones antiguas de Photutils. El contrato es consistente: devuelve `np.ndarray` de forma `(N, 3)` = `[x, y, flux]`. Probablemente esto ya fue consolidado en una iteración anterior a v57; el hallazgo del usuario documenta bien un problema de una versión anterior del proyecto, no de esta. |
| Duplicación de `resolve_object_center()` | **No confirmado como duplicado hoy.** Una sola definición (L11612). Igual que el anterior. |
| `analyse_pair_core()` vs `analise_pair()` (contratos distintos) | **El problema existe, pero ha mutado de forma.** Hoy `analyze_pair_core()` (L4701, motor real, 899 líneas) es interno; `analyze_pair()` (L10473) es un wrapper público de una sola línea que llama a `analyze_pair_with_consistency()` (L10397), la cual llama a `analyze_pair_core()` y añade verificación de consistencia científica. El comentario en L10472 dice explícitamente *"API pública única y explícita; no se realiza monkey-patch de símbolos al final del módulo"* — señal de que alguien ya intentó resolver este mismo problema. **Pero la solución es incompleta**: `analyze_series_with_ai()` (L11922, motor de series temporales) llama directamente a `analyze_pair_core()` en L11938, **saltándose `analyze_pair_with_consistency()` y por tanto el chequeo de consistencia científica**. Es el mismo problema conceptual (dos rutas con contratos distintos) reaparecido en un lugar distinto. Ver §7.1. |
| `stack_multiband()` usando `bg.background` en vez de `Background.bkg` | **No reproducido.** `stack_multiband()` (L9228) usa `bg.bkg`/`bg.rms` correctamente (L9275-9276), consistente con la clase `Background` (L1805, atributos `.bkg`/`.rms`) devuelta por `estimate_background()` (L1814). Ya corregido en esta versión. |
| `measure_proper_motion()` tratando el retorno Nx3 de `detect_point_sources()` como lista de diccionarios | **No reproducido.** L9367-9370: convierte explícitamente a `np.ndarray`, comprueba `.ndim`, `.shape[1]`, indexa con `[:, :2]`. El código incluso documenta el contrato en el docstring: *"El contrato canónico es Nx3: [x, y, flux]"* (L9364). Ya corregido en esta versión. |

**Conclusión de esta sección:** los defectos puntuales que el usuario recordaba de iteraciones anteriores ya fueron, en su mayoría, corregidos en el camino hacia v57 — buena señal de que hubo trabajo de mantenimiento real. Pero el *patrón* que los causó (rutas de ejecución paralelas con contratos divergentes) **no ha sido eliminado como clase de problema**: ha vuelto a aparecer, con síntomas distintos, en `analyze_series_with_ai` y, de forma mucho más severa, en el propio Discovery Workspace de v57 (§6). Esto es la prueba más fuerte de que se necesita arquitectura (contratos obligatorios, una sola ruta de ejecución por capa) y no una nueva ronda de parches puntuales.

---

## 4. Código muerto

### 4.1 `launch_gui_legacy()` — ~998 líneas muertas (L6608–7605)

Cero llamadas a `launch_gui_legacy` en todo el archivo (verificado por búsqueda exhaustiva). Contiene:
- Una clase `App` completa anidada (con su propio `TABLE_COLS`, manejo de hilos, plotting matplotlib embebido, exportación).
- Su propio `_QueueLogHandler` (usado también, pero definido en el mismo bloque — hay que verificar si la copia activa reutiliza esta clase o si también hace falta separarla).

Esto no es solo "líneas de más": es un **riesgo de mantenimiento activo**. Cualquier persona (o asistente de IA) que busque "la GUI" en el archivo con un editor puede encontrar primero esta versión muerta (aparece *antes* en el archivo que la versión viva) y perder tiempo modificándola, o peor, puede confundir a herramientas de análisis estático/generación de documentación.

**Acción:** eliminar completamente tras confirmar (grep + ejecución de la suite de regresión, ver Fase objetivo) que ningún script de usuario o plugin externo la invoca por nombre.

### 4.2 Candidatos adicionales de código muerto detectados

- `_profile_selection_score()` (L4654) — solo usada por la implementación muerta de §3.1.
- No se ha auditado exhaustivamente el 100% de las 255 funciones de módulo en busca de "cero llamadas" (ver §14, trabajo pendiente de Fase 2), pero el patrón encontrado en `launch_gui_legacy` sugiere fuertemente que hay más: recomendamos un barrido automatizado (`vulture` o equivalente basado en AST + grafo de llamadas) como primer paso de la Fase 2, en vez de continuar el barrido manual función por función aquí.

---

## 5. Funciones monolíticas (cuantificado)

| Función | Líneas | Ubicación | Nota |
|---|---|---|---|
| `launch_gui_legacy` | 998 | L6608–7605 | Código muerto (§4.1) — pero si estuviera viva, sería la función más grande del programa. |
| `analyze_pair_core` | 899 | L4701–5599 | **Viva, núcleo científico real.** Carga imágenes, background, registro, detección, medida, calibración, física, incertidumbre, exportación — todo en una función. |
| `launch_gui` | 675 | L12317–12991 | **Viva, GUI activa.** Construye toda la interfaz Tkinter, todos los manejadores de eventos y todos los hilos de trabajo en un único cuerpo de función. |
| `selftest` | 514 | L10561–11074 | Suite de auto-test embebida (ver §11). |
| `main` | 349 | L12993–13341 | Despachador de 55 subcomandos, secuencia de `if` (no `elif`, no tabla de despacho). |
| `analyze_pixel_science_images` | 247 | L8977–9223 | Motor de análisis píxel a píxel. |
| `check_scientific_consistency` | 182 | L7710–7891 | — |
| `write_report_pdf` | 169 | L6327–6495 | — |

**5 funciones superan las 300 líneas; 8 superan las 150; entre ellas concentran 4.033 líneas — el 28% del archivo completo.** Esto no es un problema estético: funciones de este tamaño (a) son imposibles de testear unitariamente sin invocar todo el pipeline, (b) mezclan responsabilidades (I/O + cálculo + presentación + persistencia) violando exactamente el principio que el usuario pidió proteger ("no quiero funciones gigantes que... detecten fuentes, hagan cálculos físicos, escriban JSON y además actualicen la interfaz"), y (c) son el lugar donde es más fácil introducir el tipo de bug de contrato descrito en §3.3, porque nadie puede sostener 900 líneas de estado mental a la vez.

`analyze_pair_core` en particular mezcla, en una sola función: validación de entrada, gestión de progreso/cancelación, selección de workers, carga de imágenes, cálculo de fondo, registro, detección de fuentes, extracción de perfiles, ajuste físico, cálculo de incertidumbre, exportación a JSON y llamadas a `ProcessPoolExecutor`/`ThreadPoolExecutor`. Es, en sí misma, casi todo el "Discovery Engine" que pide el usuario — pero como una única función de 899 líneas en lugar de motores separados y componibles.

---

## 6. El hallazgo arquitectónico central: tres pipelines de "descubrimiento" paralelos y no interoperables

Este es, con diferencia, el hallazgo más importante de la auditoría y la justificación más sólida para la reingeniería que pide el usuario.

### 6.1 Pipeline A — Par OIII/Hα de choque (el más antiguo y científicamente más profundo)

`analyze_pair_core()` (L4701) → `analyze_pair_with_consistency()` (L10397) → `analyze_pair()` (L10473, API pública).

Usa: `detect_point_sources` (DAOStarFinder), `estimate_background`, registro estelar, extracción de perfiles Hα/[O III], `GridManager`/`ShockGrid` (grids MAPPINGS/3MdB), cálculo de incertidumbre (`UncertaintyBudget`), corrección CCM89, y `check_scientific_consistency()`. Es el pipeline con más rigor físico acumulado. **Limitación de diseño:** asume estructuralmente un par de imágenes starless OIII+Hα de un objeto tipo remanente de choque (L4707-4709 lo exige con un `raise ValueError` si faltan). No generaliza a "cualquier imagen de cualquier objeto".

### 6.2 Pipeline B — Motor de inferencia física y evidencia v40/v41/v42/v46

`infer_physical_parameters()`, `PhysicalConstraintEngine` (L14096), `SpatialTrendAnomalyEngine` (L14144), `TemporalChangeEngine` (L14212), `ModelComparisonEngine` (L13791, AICc/BIC), `DiscoveryEvidenceEngine` (L14239), función orquestadora `discovery_v46()` (final del archivo). Este motor **no mira píxeles**: opera sobre filas de catálogo ya extraídas (el resultado del Pipeline A, o de cualquier fuente compatible), añadiendo inferencia física, detección de anomalías espaciales con FDR de Benjamini-Hochberg, análisis temporal y fusión de evidencia con **exactamente** el principio de independencia de evidencias que pide el usuario (`independent_evidence_count`, `scientific_candidate_gate = independent_evidence_count >= 2`, ver el propio código al final del archivo). Es la pieza conceptualmente más cercana al "Evidence Engine" que el usuario describe. Solo accesible desde CLI (`discover-v46`, `discover`, `spatial-anomalies`, `temporal-anomalies`, `model-compare`).

### 6.3 Pipeline C — "Discovery Workspace" (v57, el más nuevo)

`discovery_scan_observation()` (L12206) → `detect_discovery_sources()` (L12112) → `_crossmatch_discovery_sources()` (L12174) → `write_discovery_report_pdf()` (L12265). Es, en la intención, el más parecido a lo que el usuario pide: acepta *cualquier* imagen 2D (no exige par OIII/Hα), detecta fuentes de forma agnóstica al tipo de objeto (conectividad + S/N vía `scipy.ndimage.label`, no DAOStarFinder), clasifica morfológicamente (`_label_discovery_morphology`), cruza contra Gaia, y genera estados (`discovery_state`: `SCIENCE_CANDIDATE`, `UNMATCHED`, `KNOWN_VARIANT`, `ARTIFACT_REJECTED`, `QUALITY_LIMITED`, `REVIEW`) muy próximos al vocabulario que el usuario pidió (`KNOWN`, `UNMATCHED`, `ANOMALOUS`, etc.).

**El problema:** este pipeline **reimplementa desde cero** la detección de fuentes (no reutiliza `detect_point_sources`/DAOStarFinder del Pipeline A) y el cruce con catálogo (no reutiliza la infraestructura Gaia/SIMBAD más completa usada en otras partes del archivo), y **no llama a ninguna** de las clases del Pipeline B: cero referencias a `DiscoveryEvidenceEngine`, `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine`, `ModelComparisonEngine`, `infer_physical_parameters`, `AstroDiscoveryAI`, `AstroVisionAI` (verificado por búsqueda exhaustiva en el cuerpo completo de la sección v57). Es decir: **el pipeline más nuevo, el que más se parece al producto final deseado, ignora todo el motor de física, anomalías estadísticas e IA construido en las iteraciones anteriores.** Vuelve a inventar su propia noción de "estado de descubrimiento" en paralelo a la del Pipeline B, con nombres parecidos pero no idénticos ni semánticamente equivalentes.

### 6.4 Por qué esto importa más que cualquier duplicado de función

Un duplicado de función (§3) es un problema de una tarde. Tres pipelines de descubrimiento que no se hablan entre sí es un problema de **arquitectura de producto**: significa que hoy, literalmente, no existe un único lugar del código donde "imagen → candidato con evidencia física + estadística + de catálogo" ocurra de principio a fin. El usuario pide exactamente esto como núcleo del producto ("Evidence Engine... es el núcleo conceptual del producto"), y hoy no existe como una sola ruta ejecutable — existe como tres fragmentos que un ingeniero tendría que coser a mano.

Esto confirma y concreta, con evidencia de código, la intuición del encargo: **la Fase objetivo no debe "arreglar" ninguno de los tres pipelines por separado — debe fusionar sus buenas ideas (§13) en un único Discovery Engine con contratos de datos compartidos**, tal como pide el brief original.

---

## 7. Divergencias CLI vs. GUI

### 7.1 La GUI activa (`launch_gui`, L12317) no usa el motor de evidencia/física/IA

Búsqueda exhaustiva dentro del cuerpo completo de `launch_gui()` (675 líneas): **cero** referencias a `discovery_v46`, `DiscoveryEvidenceEngine`, `PhysicalConstraintEngine`, `SpatialTrendAnomalyEngine`, `TemporalChangeEngine`, `ModelComparisonEngine`, `AstroDiscoveryAI`, `AstroVisionAI`, `infer_physical_parameters`, `DiscoveryStore`, `MultiObjectPhysicsEngine`, `measure_proper_motion`, `stack_multiband`. La GUI llama únicamente a `analyze_pair`, `analyze_series_with_ai`, `discover` (una función auxiliar de descubrimiento simple, no el motor v46), `discovery_scan_observation`, `auto_pair_directory`, `generate_observatory_excel`, `export_discovery_pdf`, `export_training_workbook`, y funciones de plotting locales.

**Todos** los motores físicos, de anomalía multiparamétrica, de IA persistente y de comparación de modelos —es decir, casi todo lo que el usuario describe como núcleo científico del producto— **solo son alcanzables hoy desde la línea de comandos**, mediante subcomandos como `discover`, `discover-v46`, `physical-anomalies`, `spatial-anomalies`, `temporal-anomalies`, `model-compare`, `ai-train`, `propermotion`, `multiband`. Un usuario final de la GUI comercial nunca ve ninguno de estos resultados.

### 7.2 `analyze_series_with_ai()` se salta el chequeo de consistencia científica

`analyze_series_with_ai()` (L11922, el motor de análisis multi-época — la base natural del futuro Temporal Engine) llama directamente a `analyze_pair_core()` (L11938) en lugar de a `analyze_pair()`/`analyze_pair_with_consistency()`. Esto significa que **los payloads de análisis de series temporales carecen del bloque `scientific_consistency`** que sí reciben los análisis de un solo par (y que el generador de informe HTML consume explícitamente en L5730 para mostrar el badge PASS/FAIL de consistencia científica). Es un ejemplo concreto, vivo, de la clase de bug que el usuario pidió erradicar como principio arquitectónico ("no se aceptan dos implementaciones activas... que existen desde versiones anteriores"): dos rutas hacia el mismo núcleo de análisis, con garantías distintas, sin que nada en el sistema lo impida o lo señale.

### 7.3 CLI: 55 subcomandos, un único despachador secuencial

`main()` (L12993–13341) contiene 55 bloques `if args.cmd == "...":` consecutivos (no una tabla de despacho, no subclases de comando). Es funcional pero no escalable: cada comando nuevo añade una rama más a una función que ya tiene 349 líneas, y no hay ninguna capa de "servicio" compartida entre CLI y GUI más allá de las funciones de pipeline que ambas llaman directamente. Esto es consistente con el pedido del usuario de que "la GUI sea una capa de presentación y servicios" — hoy no lo es: GUI y CLI son dos clientes ad-hoc que llaman a funciones sueltas, no a una capa de servicios común y explícita.

---

## 8. Riesgos de corrección científica (más allá de los ya cubiertos)

1. **Vocabularios de estado incompatibles entre motores.** Se han identificado al menos tres taxonomías de estado distintas y no unificadas conviviendo en el mismo archivo:
   - Pipeline A/general: `"OBSERVABLE"`, `"NO DISPONIBLE"`, `"PROXY OBSERVACIONAL"`, `"OK"`, `"ERROR"`.
   - Pipeline C (Discovery Workspace): `"SCIENCE_CANDIDATE"`, `"ARTIFACT_REJECTED"`, `"QUALITY_LIMITED"`, `"REVIEW"`, `"KNOWN_GAIA"`, `"UNMATCHED_GAIA"`, `"KNOWN_VARIANT"`, `"UNMATCHED"`, `"MORPHOLOGY_OUTLIER"`.
   - Vocabulario que el propio usuario pide para el producto final: `KNOWN`, `KNOWN_VARIANT`, `UNMATCHED`, `ANOMALOUS`, `TRANSIENT_CANDIDATE`, `MOVING_SOURCE_CANDIDATE`, `DISCOVERY_REVIEW`.

   Ninguna de las tres coincide exactamente con las otras dos. Esto no es solo un problema estético: si en el futuro dos motores describen la misma situación observacional con palabras distintas, el Evidence Engine no podrá razonar sobre ellas de forma consistente, y la GUI tendrá que traducir ad-hoc entre vocabularios, con riesgo de errores de mapeo silenciosos.

2. **226 bloques `except Exception`** en el archivo (0 `except:` desnudos, lo cual es positivo — al menos siempre se captura `Exception` y no todo `BaseException`). Muchos de ellos son legítimos y están bien razonados (degradación elegante ante dependencias opcionales ausentes, ver §9). Pero un patrón tan extendido, sin política única sobre cuándo capturar ancho vs. estrecho, es exactamente el terreno donde puede ocultarse un error de cálculo científico real (por ejemplo, un `except Exception` alrededor de una llamada a `DAOStarFinder` — L11584 — captura legítimamente fallos de compatibilidad de API, pero capturaría con la misma facilidad un bug real introducido en el futuro, y lo convertiría silenciosamente en "0 fuentes detectadas" en vez de fallar de forma visible). El manejo de errores en `ProcessPoolExecutor` (L5107, captura específica de `(OSError, MemoryError, RuntimeError)`) demuestra que el propio código ya conoce el patrón correcto en al menos un sitio — hay que convertirlo en la norma, no en la excepción.

3. **Dependencia estructural de la existencia de imágenes starless en el Pipeline A** (`analyze_pair_core`, L4707-4709): correcto y honesto (falla explícitamente si faltan, no infiere), pero es una limitación de alcance científico que el Discovery Engine unificado deberá modelar explícitamente como una precondición del "modo de análisis de choque nebular", no como una limitación implícita de todo el sistema.

---

## 9. Seguridad — hallazgos (y buenas prácticas ya existentes que deben preservarse)

Contrario a lo que cabría temer, la postura de seguridad de este archivo es **notablemente mejor que la media** para un proyecto de este tamaño y origen. Hallazgos positivos verificados, que deben preservarse explícitamente en la reingeniería:

- **Sin `pickle` en ningún punto del archivo** (verificado, cero usos de `pickle.load`/`pickle.dump`). La persistencia de modelos usa un contenedor ZIP propio con `torch.load(..., weights_only=True)` (L4048) y `np.load(..., allow_pickle=False)` (L3659, L4049, L13395) — exactamente las mitigaciones recomendadas hoy contra deserialización insegura de modelos ML.
- **Lectura de ZIP por nombre de entrada fijo** (`z.read("state_dict.pt")`, no `.extractall()`), lo que evita path traversal / zip-slip al cargar modelos.
- **Actualizaciones verificadas de forma seria:** `update_check_https()` (L12020) exige HTTPS tanto para el manifiesto como para la URL del instalador, valida el formato del SHA256 con regex antes de usarlo. `download_verified_update()` (L12036) descarga con límite de tamaño (`max_bytes`), calcula SHA256 en streaming, compara contra el hash esperado **antes** de `os.replace()` atómico, y limpia el archivo temporal en un `finally`. Esto es exactamente el patrón que el usuario pidió ("las actualizaciones deben verificar el origen seguro y hash") — ya existe y debe conservarse casi literalmente en el producto comercial.
- **Llamadas a `subprocess` seguras:** ambos usos (`check_hardware()` L11999, `launch_verified_installer()` L12063) usan la forma de lista de argumentos (nunca `shell=True`, nunca interpolación de strings del usuario en un comando de shell). El script de PowerShell en `check_hardware()` es siempre literal/hardcodeado, nunca construido a partir de entrada externa.

**Gaps identificados que sí requieren atención en el producto comercial:**

- `launch_verified_installer()` (L12063) **confía en que el llamador ya verificó el hash** antes de invocar esta función — no vuelve a comprobar nada en el momento de lanzar el proceso. Es un patrón *verify-then-use* con una ventana TOCTOU teórica (aunque de bajo riesgo práctico en el flujo actual, de un solo proceso). Recomendación para la Fase objetivo: que el objeto que representa "instalador verificado" sea un tipo que solo pueda construirse tras una verificación exitosa (p.ej. un `VerifiedInstaller` devuelto únicamente por `download_verified_update`), de forma que sea imposible por construcción llamar a `launch_verified_installer` con una ruta no verificada.
- No hay firma de código (Authenticode) mencionada ni preparada para el propio instalador/ejecutable — necesario para una distribución comercial en Windows (SmartScreen, políticas corporativas).
- Los `HAS_*` de detección de dependencias son correctos para *funcionalidad*, pero no hay ningún mecanismo de verificación de integridad para los *grids científicos externos* más allá de lo que ya existe (`grid-trust` en CLI, registro de SHA256 auditado por el usuario — buena idea existente, ver §13) — debe generalizarse a todos los artefactos externos cargables (modelos IA, grids, curvas de filtro de terceros).
- El **manejo de rutas de Windows** (UTF-8 en consola, `sys.platform == "win32"` con `reconfigure(encoding="utf-8", errors="backslashreplace")`, L38-45) está presente y bien razonado para stdout/stderr, pero no se ha auditado aquí el comportamiento de todas las rutas de archivo con `pathlib.Path` ante nombres de archivo Unicode/longitud extendida de Windows (`\\?\`) — pendiente de revisión en Fase 2, no crítico hoy porque el producto no tiene aún empaquetado Windows real que probar.

---

## 10. Rendimiento y concurrencia

**Patrones ya presentes y correctos, a preservar:**

- Fijación de hilos de BLAS/OpenMP a 1 (`OMP_NUM_THREADS`, `OPENBLAS_NUM_THREADS`, etc., L8-11) **antes** de importar NumPy — evita la sobre-suscripción de hilos clásica cuando se combina NumPy vectorizado con `ProcessPoolExecutor`/`ThreadPoolExecutor` propios. Detalle no trivial, correcto.
- `analyze_pair_core` usa `ProcessPoolExecutor` para candidatos pesados con *fallback* automático a ejecución secuencial ante `(OSError, MemoryError, RuntimeError)` (L5107-5116) — manejo de errores específico y razonable, no un `except Exception` genérico.
- La GUI (`launch_gui`) ejecuta el trabajo pesado en `threading.Thread` con comunicación de vuelta al hilo principal mediante `queue.Queue` + `root.after(120, poll)` (L12984 aprox.) — es el patrón correcto y seguro para Tkinter (que no es thread-safe); no se ha encontrado mutación directa de widgets desde un hilo de trabajo.
- `_safe_worker_count()` ajusta el número de workers a la RAM disponible (referenciado en `analyze_pair_core`, L4732-4733).

**Riesgos y huecos identificados:**

- No hay evidencia en el código de **lectura de FITS/XISF por bloques** (memory-mapping / lectura parcial) para imágenes grandes — `load_fits` parece cargar la imagen completa en memoria como `np.float32`. Para el caso de uso objetivo (series temporales, muchas observaciones grandes) esto es un riesgo de escalabilidad real que la Fase objetivo debe resolver explícitamente (astropy soporta `memmap=True`; XISF requiere una estrategia propia).
- No se ha encontrado uso de GPU salvo el opcional de PyTorch (`torch.cuda`) para los modelos de IA — razonable, no es una carencia por sí misma, pero debe documentarse como decisión consciente (CPU-first, GPU-opcional) en la arquitectura objetivo en vez de ser un accidente de qué había disponible al escribir cada sección.
- El único mecanismo de caché explícito encontrado es el de escaneo de directorios de observatorio (`_survey_load_cache`/`_survey_cached_read`, usado por `generate_observatory_excel`). No hay una estrategia de caché general (p.ej. background estimado, WCS resuelto, cross-match de catálogo) reutilizable entre motores — cada motor que necesita el fondo de una imagen lo recalcula (`estimate_background` se llama de forma independiente en al menos 5 lugares distintos del archivo sobre lo que podría ser la misma imagen).

---

## 11. Estado de las pruebas

**Lo que existe hoy (y es de calidad real, no relleno):**

- `selftest()` (L10561, 514 líneas): suite de regresión embebida con verificaciones genuinamente científicas — convención de signo del registro estelar con desplazamiento sintético conocido (L10608-10619), validación de grids duplicados/con NaN bloqueados (L10597-10607), conversión de unidades Å↔nm en curvas de filtro, condicionamiento de la matriz de demezcla de dos filtros, calibración CCM89. Esto demuestra una cultura de testing real, no ausente — el problema es estructural, no de actitud.
- `_v46_regression_tests()` y `_v45_regression_tests()` / `_selftest_v43_scientific_hardening()`: más suites de regresión embebidas por versión, ejecutadas desde `selftest()`.
- `audit_report()` (L11076): un comando `audit` que ya existe en el CLI actual — coincidencia de nombre interesante con esta misma auditoría, pero es un reporte de estado en tiempo de ejecución (dependencias, versión), no un análisis estático del código.

**Lo que falta, de forma crítica para el objetivo comercial:**

- **Cero uso de `pytest`/`unittest`**, cero directorio `tests/`, cero integración CI. Todo el testing ocurre manualmente vía `python script.py selftest` y depende de que un humano lea la salida `[OK]/[FAIL]` en consola.
- Los tests están **mezclados con el código de producción** en el mismo archivo de 14K líneas — no hay separación entre "lo que se despliega" y "lo que se testea".
- Un único contador de fallos acumulado (`fails`, L10562) sin aislamiento entre casos — un test que lanza una excepción no controlada puede abortar la ejecución de los siguientes.
- No hay ningún test de regresión específico para los dos bugs históricos citados por el usuario (`stack_multiband`, `measure_proper_motion`) — aunque ya están corregidos en el código (§3.3), **no hay nada que impida que alguien los reintroduzca** en una futura edición, porque no existe un test que fije el contrato `Background.bkg`/`Nx3 array` de forma permanente.
- No hay ningún test que verifique "existe una única implementación pública de `launch_gui`" ni "la GUI usa el pipeline científico completo" — exactamente las dos garantías que el usuario pidió explícitamente que el testing debía imponer hacia el futuro.
- No hay smoke test de GUI (ni siquiera de "la ventana se construye sin excepción").

---

## 12. Empaquetado y preparación para Windows

**Estado actual: inexistente.** No hay `requirements.txt`, `pyproject.toml`, `setup.py`, spec de PyInstaller, ni ningún manifiesto de dependencias versionadas en el repositorio. Las dependencias solo se conocen por inspección de los `import` y las banderas `HAS_*` del propio script. Esto, combinado con el hallazgo P0 (§1), significa que **hoy no existe ninguna ruta verificada de "usuario de Windows descarga un instalador y ejecuta la app"** — ni siquiera a nivel de que el intérprete de desarrollo (3.12+) coincida con lo que produciría un build de PyInstaller típico (que hoy en día suele fijarse en 3.10/3.11 por estabilidad de wheels de `torch`/`astropy`/`scipy` en Windows).

Puntos ya favorables encontrados (a preservar): el manejo de UTF-8 de consola en Windows (§9), la ausencia de rutas de red hardcodeadas, el flujo de actualización verificada HTTPS+SHA256 (§9) que es exactamente la base correcta para un actualizador de producto comercial.

---

## 13. Ideas científicas y de ingeniería que deben conservarse explícitamente

Siguiendo el principio del encargo ("no preservar el código; preservar las buenas ideas"), estas son las ideas concretas —verificadas en el código, no supuestas— que merecen sobrevivir a la reingeniería, reimplementadas de forma modular:

1. **Separación observación/proxy/inferencia/hipótesis en los estados** (`"OBSERVABLE"`, `"PROXY OBSERVACIONAL"`, `"NO DISPONIBLE"`, y en el motor v46 la distinción explícita `priority_index_is_not_probability`). Es exactamente la disciplina epistemológica que el usuario pide para el Physical Engine — ya existe como cultura de código, hay que convertirla en un tipo de datos obligatorio.
2. **Independencia de evidencias con umbral mínimo** (`DiscoveryEvidenceEngine.evaluate_rows`, `independent_evidence_count`, `scientific_candidate_gate = independent_evidence_count >= 2 and not measurement_issue and tension_sigma >= threshold`). Esta es, literalmente, la implementación del principio central que el usuario describe para el Evidence Engine. Debe ser el punto de partida del Evidence Engine objetivo, no reinventarse.
3. **FDR de Benjamini-Hochberg y detrending espacial antes de la detección de anomalías** (`SpatialTrendAnomalyEngine`) — coincide exactamente con lo pedido para el Anomaly Engine.
4. **AICc/BIC para comparación de hipótesis físicas explícitas** (`ModelComparisonEngine`) en vez de ajustar un único modelo y asumirlo verdadero.
5. **Validación de grids por hash/procedencia** (`grid-trust` en CLI, `GridManager.validate` bloqueando grids duplicados/con NaN) — exactamente la salvaguarda que el usuario pide contra presentar una grid de demostración como una grid física publicable.
6. **Actualizador verificado HTTPS + SHA256** (§9) — listo para producción casi tal cual.
7. **Detección de dependencias opcionales con degradación explícita** (`HAS_*`) en vez de fallos de import — buen patrón para un instalador que no siempre tendrá todo (p.ej. GPU/torch) disponible.
8. **Convención de firma/signo verificada por test sintético** en el registro de imágenes (`selftest`, L10608-10619) — la disciplina de testear convenciones de signo con una verdad conocida generada sintéticamente es exactamente el tipo de test de validación científica que hay que generalizar.
9. **Salvaguardas explícitas contra sobre-interpretación**: el propio código ya rechaza tratar Optolong L-Quad Enhance como banda estrecha real salvo curva medida (mencionado por el usuario, no releído línea a línea en esta pasada pero consistente con el patrón `FILTER_BROADBAND_CONTEXT_VISIBLE` visto en L13139) y ya declara ausencia de WCS/calibración de forma explícita en varios motores (`"NOT_AVAILABLE"`, `"reason": "sin WCS/Gaia"` en L12178). Esta cultura de "declarar lo que no se sabe" debe convertirse en un contrato de tipo, no seguir siendo una convención de string.
10. **Manifiesto de ejecución reproducible** (`RunManifest`, versión + inputs + warnings) — base correcta para la procedencia (`provenance`) que pide el Candidate Engine.

---

## 14. Trabajo explícitamente fuera del alcance de esta Fase 1

Para mantener esta entrega como auditoría (no como reescritura, tal como se pidió), quedan fuera de este documento y se abordarán en las fases siguientes del plan (ver `02-ARQUITECTURA-OBJETIVO-Y-PLAN.md`):

- Barrido automatizado de código muerto al 100% de las 255 funciones (aquí se verificó el patrón con evidencia representativa, no exhaustiva función por función).
- Lectura línea a línea de los ~55 subcomandos de CLI restantes no citados explícitamente arriba.
- Diseño detallado de los contratos de datos de cada motor objetivo (Detection, Identification, Characterization, Temporal, Physical, Anomaly, Evidence, Candidate) — se esboza la dirección en el documento de arquitectura, el contrato formal (dataclasses/schemas versionados) es trabajo de Fase 4.
- Pruebas de carga/rendimiento reales con FITS/XISF grandes (requiere datos de prueba, no solo lectura de código).

---

## Resumen de hallazgos por severidad

| Severidad | Hallazgo | Referencia |
|---|---|---|
| **P0** | El archivo no parsea en Python ≤3.11 (f-string con backslash) | §1 |
| **P1** | Tres pipelines de descubrimiento paralelos, no interoperables | §6 |
| **P1** | GUI activa no usa el motor de física/anomalía/evidencia/IA | §7.1 |
| **P1** | `analyze_series_with_ai` se salta el chequeo de consistencia científica | §7.2 |
| **P1** | Cero tests automatizados/CI pese a existir una buena suite de regresión embebida | §11 |
| **P1** | Cero empaquetado/manifiesto de dependencias para Windows | §12 |
| **P2** | `select_optimal_profile_candidates` duplicada (una copia muerta) | §3.1 |
| **P2** | `launch_gui_legacy` — ~998 líneas de código muerto con clase `App` duplicada | §4.1 |
| **P2** | 5 funciones >300 líneas, 28% del archivo en funciones monolíticas | §5 |
| **P2** | Tres vocabularios de estado incompatibles entre motores | §8.1 |
| **P3** | 226 `except Exception` sin política unificada | §8.2 |
| **P3** | Sin lectura por bloques de FITS/XISF grandes | §10 |
| **P3** | `launch_verified_installer` sin re-verificación (TOCTOU teórico) | §9 |
