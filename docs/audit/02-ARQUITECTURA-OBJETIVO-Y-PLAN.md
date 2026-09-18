# AstroPhysics Suite — Arquitectura Objetivo y Plan de Migración

Este documento es la contraparte propositiva de `01-AUDITORIA-TECNICA-FASE1.md`. No se implementa nada todavía: es la propuesta técnica concreta que, una vez validada por el usuario, guiará las fases 2 en adelante.

Principio rector, tomado literalmente del encargo: **el centro del producto no es la imagen — es el candidato científico y su evidencia.** Toda decisión de arquitectura de abajo se subordina a eso: cualquier módulo que no contribuya, directa o indirectamente, a producir o auditar un `Candidate` con su `Evidence` es secundario.

---

## 1. Estructura de paquetes propuesta

```
astrophysics_suite/
├── core/            # tipos base, config, excepciones, unidades, logging, provenance
├── models/          # contratos de datos versionados: Observation, Candidate, Evidence, Project
├── io/               # FITS/XISF, WCS, lectura por bloques, caché de disco
├── detection/        # Detection Engine: puntuales, extendidas, blobs, filamentos, arcos...
├── artifacts/         # Artifact Rejection Engine
├── astrometry/        # registro, WCS, resolución de centro, Gaia (astrometría)
├── photometry/        # calibración, PSF, S/N, perfiles, color
├── spectroscopy/      # líneas, ratios Hα/[O III], [N II], extinción CCM89
├── physics/           # Rankine-Hugoniot, cooling, grids MAPPINGS/3MdB, incertidumbre, AICc/BIC
├── catalogs/          # Identification Engine: Gaia, SIMBAD, catálogos especializados
├── temporal/          # Temporal Engine: series de épocas, variabilidad, movimiento propio
├── anomaly/           # Anomaly Engine: vector de anomalías, FDR, tendencias espaciales
├── discovery/         # orquestación: une detection→...→evidence en una sola ruta
├── ai/                # AstroVision, Discovery AI, Temporal AI — evidencia adicional, no veredicto
├── evidence/          # Evidence Engine: fusión auditable, independencia de evidencias
├── projects/          # persistencia de proyectos, revisiones humanas, datasets de entrenamiento
├── reports/           # PDF/HTML/Excel — consumen modelos, no calculan ciencia
├── services/          # capa que GUI y CLI consumen por igual (nunca lógica científica aquí)
├── gui/               # presentación pura (Tkinter u otro), sin cálculo científico
├── cli/               # comandos, cada uno delega a services/
├── config/            # configuración externa (YAML/TOML), rutas de datos de usuario
├── packaging/         # spec de PyInstaller, instalador, actualizador
└── tests/
    ├── unit/
    ├── integration/
    ├── regression/
    ├── scientific_validation/
    ├── gui_smoke/
    └── e2e/
```

**Regla de dependencia (para que esto no vuelva a degenerar en un monolito):** las capas de la izquierda no pueden importar de las de la derecha. `gui/` y `cli/` solo pueden importar `services/`. `services/` es la única capa autorizada a importar de `detection/`, `physics/`, `evidence/`, etc. Ningún motor científico importa `tkinter`, directa ni indirectamente — esto se hace cumplible con un test de arquitectura (§4.3) que falla el build si aparece.

Esta estructura es una evolución directa de la propuesta por el usuario (`app, core, models, io, detection, artifacts, astrometry, photometry, spectroscopy, physics, catalogs, temporal, anomaly, discovery, ai, evidence, projects, reports, services, gui, config, logging, tests`) — se ha mantenido casi literal porque, tras la auditoría, es coherente con las 53 clases y 255 funciones reales inventariadas en la Fase 1 (§2.2 del documento de auditoría). No se ha encontrado ninguna razón técnica para desviarse de ella; sí se añade `packaging/` de forma explícita porque hoy no existe en absoluto (§12 de la auditoría) y es un requisito de primera clase, no un detalle final.

---

## 2. Los motores especializados y sus contratos

Cada motor recibe una entrada tipada y devuelve una salida tipada — nunca un `dict` suelto sin schema. Esto es la corrección estructural directa del hallazgo §6/§8.1 de la auditoría (vocabularios de estado incompatibles, tres pipelines no interoperables).

### 2.1 Detection Engine (`detection/`)

- **Entrada:** `Observation` (una o varias imágenes calibradas, con o sin WCS).
- **Salida:** `list[Detection]` — puntuales, extendidas, blobs, filamentos, arcos, conchas, dobles, halos, jets, condensaciones. Cada `Detection` lleva: posición en píxeles (y en cielo si hay WCS), morfología cruda (área, elongación, compacidad), banda(s) de origen, método de detección usado, y un puntero a la región de origen (para trazabilidad).
- **Consolida:** la lógica de `detect_point_sources`/DAOStarFinder (Pipeline A de la auditoría) y la de `detect_discovery_sources` (Pipeline C) bajo una interfaz común con **estrategias intercambiables** (puntual vía DAOStarFinder, extendida vía conectividad+S/N, filamentaria vía Hessian/Canny — estas dos últimas ya existen como `HessianFilamentStrategy`/`CannyFilamentStrategy` en el código actual, L2342-2383, y encajan aquí sin reescritura conceptual). Multibanda se resuelve fusionando detecciones por banda con matching espacial, reutilizando la idea ya presente en `discovery_scan_observation` (L12224-12246) de la auditoría.

### 2.2 Artifact Rejection Engine (`artifacts/`)

- **Entrada:** `list[Detection]` + metadatos de la observación (PSF, saturación, calidad de registro).
- **Salida:** cada `Detection` anotada con `ArtifactAssessment` (ruido, hot pixel, rayo cósmico, saturación, defecto de PSF, reflejo, gradiente, donut, error de registro, residuo de stacking/sustracción, traza de avión/satélite) — nunca elimina silenciosamente, marca y explica. Se ejecuta **antes** de que nada se considere candidato, tal como pide el usuario.
- **Reutiliza:** la lógica de `_label_discovery_morphology` (L12095, la línea `elongation >= 8.0 → ARTIFACT_REJECTED` etc.) como punto de partida, generalizada a reglas explícitas y configurables en vez de umbrales fijos en código.

### 2.3 Identification Engine (`catalogs/`)

- **Entrada:** `Detection` con posición celeste (requiere WCS válido).
- **Salida:** `IdentificationResult` con estado de entre exactamente estos valores (el vocabulario único, sustituyendo los tres actuales — §8.1 de la auditoría): `KNOWN`, `KNOWN_VARIANT`, `UNMATCHED`, `ANOMALOUS`, `TRANSIENT_CANDIDATE`, `MOVING_SOURCE_CANDIDATE`, `DISCOVERY_REVIEW`. Cada estado lleva el/los `catalog_matches` (Gaia, SIMBAD, catálogos especializados) y `catalog_non_matches` con radio de búsqueda y razón.
- **Reutiliza:** la infraestructura de consulta a Gaia/SIMBAD ya existente y probada (`query_gaia_sources`, resolución de nombres SIMBAD con alias conservadores, L11591-11609), unificando los dos cross-matchers actualmente redundantes (`_crossmatch_discovery_sources` del Pipeline C vs. la lógica de Gaia del resto del archivo).

### 2.4 Characterization Engine (`photometry/` + `spectroscopy/` + `astrometry/`)

- **Entrada:** `Detection` + `Observation`.
- **Salida:** `CharacterizationResult`: posición, coordenadas celestes, tamaño angular, área, elongación, elipticidad, FWHM, flujo + error, S/N, brillo superficial, color, perfiles, longitud/curvatura de filamento, ratios entre bandas (Hα, [O III], [O III]/Hα), movimiento propio, variabilidad — cada campo con su propia incertidumbre y una etiqueta de procedencia (`measured` / `derived` / `not_available`), nunca un valor "aparecido de la nada".
- **Consolida:** casi todo el contenido físico ya presente en `analyze_pair_core` (§5 de la auditoría) pero **separado en componentes testeables individualmente**, en vez de una función de 899 líneas.

### 2.5 Temporal Engine (`temporal/`)

- **Entrada:** `list[CharacterizationResult]` de la misma posición celeste en distintas épocas, con sus incertidumbres y metadatos de calidad/cobertura de cada época.
- **Salida:** `TemporalAssessment` con evidencia de aparición, desaparición, variabilidad, cambio morfológico, cambio de color/ratio, desplazamiento espacial — cada uno con su propia significancia estadística, nunca una conclusión binaria sin incertidumbre.
- **Consolida:** `measure_proper_motion` (ya correcto, §3.3 auditoría), `TemporalChangeEngine` (v46) y la lógica de `analyze_series_with_ai`, **corrigiendo el bypass del chequeo de consistencia** encontrado en §7.2 de la auditoría — en la arquitectura objetivo, el Temporal Engine consume `CharacterizationResult` ya validados, por lo que el bug deja de ser posible por construcción (no hay una ruta alternativa que se salte la validación).

### 2.6 Physical Engine (`physics/`)

- **Entrada:** `CharacterizationResult` (+ familia de objeto declarada).
- **Salida:** `PhysicalInference`, con separación explícita y obligatoria en el tipo entre: **observable** (medido directamente), **proxy** (derivado con un modelo simple y declarado), **inferencia de modelo** (requiere grid/modelo físico validado, con hipótesis, dominio de validez e incertidumbre propagada), e **hipótesis** (no confirmada, solo plausible). Ningún ratio se convierte en velocidad/edad/densidad sin pasar por un `PhysicalModel` versionado con procedencia y hash verificado.
- **Consolida:** `ShockGrid`/`GridManager`/Rankine-Hugoniot, `CoolingCurve`, `MappingsGridLoader` (validación por hash — ya existe, §13.5 auditoría), `UncertaintyBudget`, `ModelComparisonEngine` (AICc/BIC) y `MultiObjectPhysicsEngine` — todas piezas que la auditoría confirma como científicamente sólidas hoy, simplemente dispersas y no todas alcanzables desde el mismo punto de entrada.

### 2.7 Anomaly Engine (`anomaly/`)

- **Entrada:** `CharacterizationResult` + `PhysicalInference` + población de referencia.
- **Salida:** `AnomalyVector` — **nunca un score único opaco**: campos separados `photometric`, `morphological`, `spectral`, `temporal`, `astrometric`, `spatial`, `physical`, cada uno con valor, incertidumbre, método y referencia. Exactamente lo pedido por el usuario.
- **Consolida:** `SpatialTrendAnomalyEngine` (FDR de Benjamini-Hochberg + detrending espacial, ya implementado y correcto según la auditoría) y `PhysicalConstraintEngine`, generalizando a las demás dimensiones de anomalía que hoy no tienen motor propio (fotométrica, morfológica pura).

### 2.8 Discovery AI (`ai/`)

Cuatro componentes, cada uno **una fuente de evidencia más**, nunca un veredicto:
- **AstroVision** (`ai/vision.py`): representaciones visuales aprendidas de imágenes reales — consolida `AstroVisionAI`/`_AstroConvAutoencoder`, ya con buena disciplina de seguridad de carga (§9 auditoría).
- **Physical AI**: relaciones observable↔propiedad física aprendidas de datos reales etiquetados — consolida `AstroDiscoveryAI`/`ViabilityModel`.
- **Discovery AI**: combinaciones de características infrecuentes — mismo origen que el anterior, responsabilidad separada.
- **Temporal AI**: apoyo a la detección de cambios entre épocas, integrado con el Temporal Engine (§2.5), no sustituyéndolo.
- Cada modelo entrenado lleva procedencia obligatoria: versión, dataset, nº de muestras, features, alcance declarado, y **marca explícita datos reales vs. sintéticos** (principio ya presente en `real-dataset`/`real-ai-train` del CLI actual — preservar y formalizar).

### 2.9 Evidence Engine (`evidence/`) — núcleo del producto

- **Entrada:** las salidas tipadas de 2.2 a 2.8 para una misma `Detection`.
- **Salida:** `EvidenceChain` — lista estructurada y auditable de piezas de evidencia (WCS válido, incertidumbre de posición, matches/non-matches de catálogo, S/N, morfología, ratios físicos, comportamiento temporal, movimiento, comparación de modelos, estado de artefactos, novedad visual/física), más un **índice de prioridad explicable y desmontable** (nunca "Discovery Score = 94" sin desglose).
- **Es, casi literalmente, `DiscoveryEvidenceEngine` (L14239 del archivo actual) ya implementado con el principio correcto** (`independent_evidence_count >= 2`, `priority_index_is_not_probability`, `human_verification_required`). La Fase objetivo generaliza este motor —hoy solo alimentado por el Pipeline B (§6.2 auditoría)— para que sea el **único** punto de fusión de evidencia, alimentado también por los pipelines A y C unificados.

### 2.10 Candidate Engine (`models/candidate.py` + `projects/`)

Modelo de datos versionado y serializable (propuesta concreta de campos, todos ya con equivalente disperso en el código actual):

```python
@dataclass(frozen=True)
class Candidate:
    schema_version: int
    candidate_id: str            # estable, único, auditable
    observation_id: str
    created_at: datetime
    position: SkyPosition         # px + RA/Dec + incertidumbre
    morphology: MorphologySummary
    size: SizeSummary
    flux: FluxSummary             # valor + error + banda
    snr: float
    bands: list[str]
    catalog_matches: list[CatalogMatch]
    catalog_non_matches: list[CatalogQuery]
    temporal_evidence: TemporalAssessment | None
    motion_evidence: MotionAssessment | None
    physical_evidence: PhysicalInference | None
    anomaly_evidence: AnomalyVector | None
    ai_evidence: list[AIAssessment]
    artifact_checks: list[ArtifactAssessment]
    quality: QualitySummary
    provenance: Provenance         # versión de pipeline, modelo, grid, hash
    identification_state: IdentificationState   # el vocabulario único de §2.3
    review_state: ReviewState      # PENDING / KEPT / REJECTED / FLAGGED
    review_notes: list[ReviewNote]
```

Cada `Candidate` vive dentro de un `Project` persistente (`projects/`) que permite revisar, descartar, conservar, etiquetar, y **exportar el resultado de esas revisiones como dataset de entrenamiento** — cerrando el ciclo OBSERVACIÓN REAL → CANDIDATOS → REVISIÓN HUMANA → LABEL → DATASET → ENTRENAMIENTO → MODELO que pide el usuario.

---

## 3. GUI objetivo

### 3.1 Flujo

```
NUEVA OBSERVACIÓN → CARGAR IMÁGENES → ANALIZAR → DISCOVERY WORKSPACE → CANDIDATOS → EVIDENCIA → REVISIÓN → INFORME
```

- **Pantalla principal:** observación activa + lista de candidatos (ordenada por índice de prioridad, filtrable por estado de identificación/revisión). No una colección de parámetros.
- **Vista de candidato:** imagen, mapas, multibanda, morfología, catálogos, temporalidad, física, IA, chequeo de artefactos — es decir, la `EvidenceChain` completa renderizada, con cada componente desmontable/inspeccionable (clic en "anomalía física alta" muestra el `AnomalyVector.physical` exacto con su método y referencia).
- **Acciones de revisión:** conservar / descartar / marcar para revisión, exportar Discovery Case. **La aplicación nunca declara un descubrimiento oficial** — solo genera candidatos para revisión humana, principio que además de ser buena ciencia es la protección legal/reputacional correcta para un producto comercial.
- **Opciones avanzadas** (parámetros de grids, umbrales de detección, configuración de workers): en un panel separado/colapsable, nunca en el flujo principal — resolviendo directamente la queja del usuario de que la GUI actual (y sobre todo la CLI de 55 subcomandos) se siente como "un protocolo" y no como software comercial.

### 3.2 Separación de capas (obligatoria, verificable)

- La GUI **llama exclusivamente a `services/`**, nunca a `detection/`, `physics/`, etc. directamente.
- `services/` expone operaciones asíncronas con progreso y cancelación (`Job`, `JobProgress`, `JobHandle.cancel()`) — generalización del patrón `Queue` + `root.after(...)` ya usado correctamente en `launch_gui` (§10 auditoría), pero ahora reutilizable por CLI, GUI y (a futuro) una API.
- Los motores científicos son importables y ejecutables **sin Tkinter** — se verifica con un test de arquitectura que falla si cualquier módulo fuera de `gui/` importa `tkinter` (ver §4.3).
- Framework de GUI: se mantiene Tkinter/ttk en el corto plazo (ya funciona, ya tiene el patrón de hilos correcto, no bloquea la reingeniería) pero la capa de `services/` se diseña agnóstica al framework de presentación, dejando abierta una migración futura (p.ej. a una GUI más moderna) sin tocar ningún motor científico.

---

## 4. Testing, calidad y empaquetado — objetivos concretos

### 4.1 Pirámide de tests

- **Unitarias:** cada motor (`detection/`, `physics/`, `anomaly/`, etc.) con datos sintéticos de verdad conocida — generalizando la disciplina ya vista en `selftest()` (convención de signo de registro con desplazamiento sintético conocido, §13.8 auditoría).
- **Integración:** pipelines completos (`Observation → Candidate`) con fixtures de FITS sintéticos pequeños.
- **Regresión:** un test por cada bug histórico conocido, incluyendo explícitamente los dos citados por el usuario aunque ya estén corregidos (`Background.bkg` no `bg.background`; `detect_point_sources` devuelve `(N,3)` y se consume como array, no como lista de dicts) — para que **nunca más puedan reaparecer sin que el CI lo note**, y el hallazgo de `analyze_series_with_ai` saltándose la consistencia científica (§7.2 auditoría).
- **Validación científica:** unidades, dominios de validez de cada `PhysicalModel`, verificación de que ninguna inferencia se presenta con más certeza de la que sus datos permiten.
- **Smoke de GUI:** la ventana se construye e inicializa sin excepción, con y sin dependencias opcionales presentes.
- **E2E:** FITS/XISF → QC → detección → rechazo de artefactos → identificación → caracterización → anomalía → evidencia → candidato → informe, con al menos un caso "conocido" (debe identificar) y uno "sin catálogo" (debe generar `UNMATCHED`, no una afirmación de descubrimiento).

### 4.2 Guardas estructurales (impiden que la Fase 1 se repita)

- Test que falla si existe más de una definición pública de `launch_gui` (o de cualquier función marcada como API pública única).
- Test que falla si `gui/` invoca directamente cualquier símbolo de `detection/`, `physics/`, `anomaly/`, `evidence/` sin pasar por `services/`.
- Test que falla si el árbol de importación de cualquier módulo fuera de `gui/` incluye `tkinter`.
- `ast.parse()` del código fuente contra la versión mínima de Python objetivo, como parte del CI — hallazgo P0 de la auditoría (§1) convertido en guarda permanente.
- Linter de código muerto (`vulture` o equivalente) en CI, con lista de excepciones explícita y revisada — para que un nuevo `launch_gui_legacy` no pueda acumularse en silencio otra vez.

### 4.3 Empaquetado Windows

- `pyproject.toml` con dependencias fijadas (incluyendo extras opcionales `torch`, `gpu`).
- Spec de PyInstaller con la versión mínima de Python fijada y verificada en CI (3.11, salvo que el usuario prefiera 3.12+ — a decidir explícitamente, no por defecto del entorno de desarrollo).
- Configuración externa (YAML/TOML) para rutas de datos de usuario, caché, modelos IA, proyectos y logs, siguiendo las convenciones de Windows (`%APPDATA%`/`%LOCALAPPDATA%`), con modo portátil opcional.
- Reutilización directa del flujo de actualización verificada ya existente (§13.6 auditoría) como base del actualizador de producto.
- Firma de código (Authenticode) del instalador y del ejecutable — pendiente de decisión de negocio (coste de certificado), documentar como requisito antes del lanzamiento comercial.

---

## 5. Plan de migración por fases

Fase 1 (este documento y su compañero de auditoría) ya está completa. Las siguientes:

| Fase | Objetivo | Entregable |
|---|---|---|
| **2 — Mapeo de dependencias y contratos** | Grafo de llamadas completo (qué función llama a qué), barrido automatizado de código muerto al 100%, contratos de entrada/salida documentados función por función para las ~30 funciones que alimentarán los motores objetivo. | Documento de contratos + grafo de dependencias. |
| **3 — Eliminación de duplicados y legado confirmado** | Eliminar `launch_gui_legacy` y `_profile_selection_score`/copia muerta de `select_optimal_profile_candidates` tras confirmar cero referencias externas (scripts de plugin del usuario). Unificar `analyze_series_with_ai` para que pase por `analyze_pair_with_consistency`. | PR de limpieza, con los tests de regresión de la Fase 5 ya escritos primero (test-first sobre el comportamiento a preservar). |
| **4 — Contratos de datos y arquitectura objetivo** | Definir como `dataclasses`/modelos versionados: `Observation`, `Detection`, `CharacterizationResult`, `PhysicalInference`, `AnomalyVector`, `EvidenceChain`, `Candidate`, `Project`. Definir el vocabulario único de estados (§2.3). | Paquete `models/` completo, con tests unitarios de (de)serialización. |
| **5 — Tests de regresión** | Portar `selftest()` y las suites `_v4x_regression_tests` a `pytest`, añadir los tests de guarda estructural (§4.2), fijar los dos bugs históricos y el bypass de consistencia como regresiones permanentes. | Suite `tests/` ejecutable en CI, sin dependencia del archivo monolítico. |
| **6 — Refactor progresivo** | Extraer motores de `analyze_pair_core`/`launch_gui` hacia los paquetes objetivo, función por función, manteniendo verdes los tests de la Fase 5 en todo momento (nunca "big bang"). | Paquetes `detection/`, `astrometry/`, `photometry/`, `physics/` poblados; `analyze_pair_core` reducida a orquestación fina. |
| **7 — Integración del Discovery Engine** | Fusionar los tres pipelines (§6 auditoría) en una única ruta `Observation → Candidate` a través de `evidence/`. El Pipeline C (Discovery Workspace) pasa a ser el "modo genérico" y el Pipeline A el "modo choque nebular especializado", ambos alimentando el mismo `EvidenceChain`. | Paquete `discovery/` orquestador único. |
| **8 — Integración de GUI** | GUI nueva desde cero sobre `services/`, flujo de §3.1, sin heredar `launch_gui` actual salvo el patrón de hilos ya validado. | GUI comercial funcional sobre el pipeline unificado. |
| **9 — Empaquetado comercial** | PyInstaller, instalador, actualizador, firma de código, modo portátil, recuperación de errores. | Instalador Windows 10/11 verificado end-to-end. |

Cada fase se cierra únicamente cuando su suite de tests correspondiente está en verde — no se avanza de fase por calendario, se avanza por evidencia.

---

## 6. Próximo paso inmediato propuesto

Antes de tocar código de producción, la Fase 2 (mapeo de dependencias y contratos) es puramente analítica y de bajo riesgo — recomendamos empezarla a continuación si el usuario aprueba esta arquitectura objetivo. Alternativamente, si el usuario prefiere empezar por el hallazgo P0 (el archivo no arranca en Python ≤3.11), esa es una corrección de una línea que puede hacerse de forma aislada, con un test de regresión (`ast.parse` contra 3.11) antes de cualquier otro trabajo, sin esperar al resto del plan.
