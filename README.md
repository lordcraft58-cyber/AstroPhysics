# AstroPhysics Suite

Estación de descubrimiento astrofísico asistida por ordenador. Analiza observaciones astronómicas reales para detectar fuentes y estructuras, identificarlas contra catálogos, caracterizarlas, detectar anomalías y cambios temporales, y generar **candidatos científicos auditables para revisión humana** — nunca descubrimientos automáticos.

Filosofía central: **IMÁGENES → DETECCIÓN → IDENTIFICACIÓN → CARACTERIZACIÓN → COMPARACIÓN → ANOMALÍAS → EVIDENCIAS → CANDIDATO CIENTÍFICO → REVISIÓN HUMANA**.

## Estado del proyecto

En reingeniería activa. El código heredado (`legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py`, ~14.300 líneas) contiene rigor científico acumulado a lo largo de muchas iteraciones, pero también fragmentación arquitectónica significativa. La Fase 1 (auditoría completa) ya se ha realizado:

- [`docs/audit/01-AUDITORIA-TECNICA-FASE1.md`](docs/audit/01-AUDITORIA-TECNICA-FASE1.md) — inventario completo, duplicados, código muerto, funciones monolíticas, hallazgos de seguridad/rendimiento/testing, y el hallazgo central: tres pipelines de "descubrimiento" paralelos y no interoperables.
- [`docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md`](docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md) — arquitectura de paquetes objetivo, contratos de los motores especializados (Detection, Artifact Rejection, Identification, Characterization, Temporal, Physical, Anomaly, Discovery AI, Evidence, Candidate), GUI comercial objetivo, y plan de migración por fases.
- [`docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md`](docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md) — Fase 2: grafo de llamadas completo, barrido de código muerto al 100% (23 de 307 entidades), cuantificación exacta de qué motores son alcanzables desde la GUI vs. solo desde la CLI (78 entidades CLI-only), y contratos reales de las funciones/clases que alimentarán cada motor objetivo.
- [`docs/audit/04-FASE3-DUPLICADOS-Y-LEGADO-ELIMINADOS.md`](docs/audit/04-FASE3-DUPLICADOS-Y-LEGADO-ELIMINADOS.md) — Fase 3: corrección del bug P0 (Python <3.11), corrección del bypass de consistencia científica, conexión de la suite v46 a `selftest()`, y eliminación de las 17 entidades muertas confirmadas (−1.310 líneas), todo respaldado por la suite de tests nueva en `tests/`.
- [`docs/audit/05-FASE4-CONTRATOS-DE-DATOS.md`](docs/audit/05-FASE4-CONTRATOS-DE-DATOS.md) — Fase 4: paquete `astrophysics_suite/` con los contratos de datos versionados (`Observation`, `Detection`, `CharacterizationResult`, `PhysicalInference`, `AnomalyVector`, `EvidenceChain`, `Candidate`, `Project`), el tipo `Quantity` (valor + incertidumbre + estatus epistémico) y el vocabulario único de `IdentificationState`, con un adaptador probado contra una ejecución real del pipeline heredado.
- [`docs/audit/06-FASE5-TESTS-DE-REGRESION.md`](docs/audit/06-FASE5-TESTS-DE-REGRESION.md) — Fase 5: prueba de humo de GUI que **encontró y corrigió un `KeyError` que impedía arrancar `launch_gui()` en cualquier versión de Python**, guardas estructurales pedidas por el encargo (una sola implementación por función crítica; la GUI debe usar el pipeline completo — hoy `xfail` documentado; sin Tkinter en la capa de ciencia), y la suite conectada por primera vez a CI (`.github/workflows/tests.yml`).
- [`docs/audit/07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md`](docs/audit/07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md) — Fase 6 (primer corte): `io/` y `detection/` poblados de extremo a extremo — carga real de FITS → `Observation`/`ImageRef`, y detección real de fuentes puntuales → `Detection`, delegando el algoritmo en el código heredado ya probado (patrón *strangler fig*) y verificado con FITS sintéticos reales, no simulaciones.
- [`docs/audit/08-FASE6-MOTORES-RESTANTES.md`](docs/audit/08-FASE6-MOTORES-RESTANTES.md) — Fase 6 (resto de motores): `artifacts/`, `catalogs/`, `photometry/`, `physics/`, `anomaly/`, `temporal/` y `evidence/` poblados. Incluye un hallazgo científico real: las comprobaciones de consistencia interna de `PhysicalConstraintEngine` (edad Sedov, temperatura de choque) son **inalcanzables en la ruta de producción real** (`DiscoveryEvidenceEngine.evaluate_rows`) por un desajuste de contrato entre `infer_physical_parameters` y lo que esas comprobaciones necesitan leer.

## Arquitectura objetivo (en construcción)

```
astrophysics_suite/
├── core/        # ValueKind, IdentificationState, ReviewState, ArtifactKind, MorphologyClass, QualityLevel, Quantity, Provenance
├── models/      # Observation, Detection, CharacterizationResult, PhysicalInference, AnomalyVector,
│                # TemporalEvidence, MotionEvidence, EvidenceChain, Candidate, Project, legacy_adapter
├── io/          # carga real de FITS -> Observation/ImageRef
├── detection/   # detección real de fuentes puntuales -> Detection
├── artifacts/   # filtro morfológico -> ArtifactCheck/QualityCheckItem
├── catalogs/    # identificación Gaia -> IdentificationState/CatalogMatch
├── photometry/  # calidad por fuente -> CharacterizationResult
├── physics/     # inferencia física por fila -> PhysicalInference
├── anomaly/     # tensión física -> AnomalyVector.physical
├── temporal/    # variabilidad multiépoca -> TemporalEvidence
└── evidence/    # fusión de evidencia -> EvidenceChain
```

Los nueve motores conceptuales tienen ya un primer corte real y probado (Fase 6, ver `docs/audit/07-...` y `08-...`). Falta fusionarlos en una única ruta `Observation → Candidate` (Fase 7) y las extensiones a los otros pipelines (choque OIII/Hα completo, motor v46).

## Tests

```
pip install -r requirements-test.txt
pytest tests/
```

No es un programa de astrofotografía ni compite con PixInsight/Siril en procesamiento estético. El objetivo es descubrimiento científico a partir de imágenes reales de telescopio.
