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
- [`docs/audit/09-FASE7-DISCOVERY-ENGINE.md`](docs/audit/09-FASE7-DISCOVERY-ENGINE.md) — Fase 7: `discovery/pipeline.py` orquesta los nueve motores en una ruta real **`Observation → list[Candidate]`**, probada de extremo a extremo con FITS sintéticos reales (sin mocks). Demuestra además que physics + anomaly + evidence componen correctamente en el modo especializado (choque OIII/Hα), aunque todavía no partan de píxeles reales.
- [`docs/audit/10-FASE8-GUI.md`](docs/audit/10-FASE8-GUI.md) — Fase 8: GUI comercial completa en Tkinter (`gui/`, `services/`) — proyecto, nueva observación, análisis con progreso/cancelación, candidatos filtrables, detalle con cadena de evidencia completa y revisión humana, configuración avanzada, diagnóstico de equipo. **Conservada como referencia de diseño**; no es la interfaz final del producto (ver Fase 9).
- [`docs/audit/11-FASE9-IRAF-PIXINSIGHT-PLAN.md`](docs/audit/11-FASE9-IRAF-PIXINSIGHT-PLAN.md) — Fase 9, plan: integrar las capacidades clásicas de IRAF (reducción de CCD, fotometría de apertura y PSF, espectroscopía 1D/2D, astrometría/WCS, utilidades de imagen) reimplementadas con numpy/scipy propios, bajo un taller estilo PixInsight en Qt que sustituye a la GUI en Tkinter.
- [`docs/audit/12-FASE9.6-QT-PIXINSIGHT-GUI.md`](docs/audit/12-FASE9.6-QT-PIXINSIGHT-GUI.md) — Fase 9.6: taller de procesamiento `qt_app/` (PySide6) — MDI, explorador de procesos arrastrable, STF no destructivo, consola integrada, procesos reales cableados (rayos cósmicos, overscan, fotometría de apertura, ajuste de continuo), y migración completa del flujo de revisión de candidatos (Fase 8) al mismo shell — panel acoplable filtrable, detalle con cadena de evidencia, Conservar/Descartar/Marcar, todo sobre `services/discovery_service.py` sin cambios.

## Arquitectura objetivo (en construcción)

```
astrophysics_suite/
├── core/          # ValueKind, IdentificationState, ReviewState, ArtifactKind, MorphologyClass, QualityLevel, Quantity, Provenance
├── models/        # Observation, Detection, CharacterizationResult, PhysicalInference, AnomalyVector,
│                  # TemporalEvidence, MotionEvidence, EvidenceChain, Candidate, Project, legacy_adapter
├── io/            # carga real de FITS -> Observation/ImageRef
├── detection/     # detección real de fuentes puntuales -> Detection
├── artifacts/     # filtro morfológico -> ArtifactCheck/QualityCheckItem
├── catalogs/      # identificación Gaia -> IdentificationState/CatalogMatch
├── photometry/    # calidad por fuente -> CharacterizationResult; apertura (apphot); PSF (daophot)
├── physics/       # inferencia física por fila -> PhysicalInference
├── anomaly/       # tensión física -> AnomalyVector.physical
├── temporal/      # variabilidad multiépoca -> TemporalEvidence
├── evidence/      # fusión de evidencia -> EvidenceChain
├── discovery/     # orquestación real: Observation -> list[Candidate] (modo genérico)
├── imtools/       # aritmética con incertidumbre + rayos cósmicos (L.A.Cosmic) -- imtools de IRAF
├── reduction/     # overscan, combinación, bias/dark/flat maestros, calibración, píxeles defectuosos, franjas -- ccdred de IRAF
├── astrometry/    # ajuste de WCS (ccmap) + registro/reproyección -- images.coords de IRAF
└── spectroscopy/  # traza (suma/óptima), longitud de onda, calibración en flujo, continuo -- onedspec/twodspec de IRAF

services/    # orquestación de trabajos en segundo plano (sin GUI) -- SessionState, DiscoveryJob, HardwareCheckJob
gui/         # GUI comercial en Tkinter (Fase 8) -- conservada como referencia, no es la interfaz final
qt_app/      # taller de procesamiento PixInsight/Qt (Fase 9.6) -- la interfaz final del producto
             # candidates/ -- flujo de revisión de candidatos (Fase 8) migrado al mismo shell
```

Los nueve motores conceptuales del Discovery Engine tienen un primer corte real y probado, y `discovery/pipeline.py` los orquesta en una ruta ejecutable de extremo a extremo (Fase 7). La Fase 9 añade, en paralelo, un núcleo IRAF propio completo (reducción, fotometría de apertura/PSF, astrometría, espectroscopía) y el taller Qt que lo expone. Queda por delante: extraer la medición de observables físicos de `analyze_pair_core` para que el modo especializado de descubrimiento (choque OIII/Hα) parta de píxeles reales; conectar calibración/fotometría/espectroscopía al Discovery Engine; y migrar el flujo de revisión de candidatos al shell Qt (ver "Qué queda" en `docs/audit/12-...`).

## Tests

```
pip install -r requirements-test.txt
pytest tests/
```

Para ejecutar y probar el taller Qt (`qt_app/`) además de la suite general:

```
pip install -r requirements-test.txt -r requirements-gui.txt
python -m qt_app
```

Ya no es cierto que este proyecto no compita en procesamiento: la Fase 9 integra deliberadamente las capacidades clásicas de reducción/análisis de IRAF bajo una interfaz inspirada en PixInsight. Lo que no cambia es el objetivo último: generar **candidatos científicos auditables para revisión humana** a partir de imágenes reales de telescopio, nunca descubrimientos automáticos.

## Empaquetado comercial de Windows

`packaging/` construye el ejecutable y el instalador de Windows del
taller (`qt_app/`) -- ver [`packaging/README.md`](packaging/README.md)
para el flujo completo, las decisiones de diseño (modo `onedir`, qué se
excluye) y qué se verificó de verdad frente a lo que necesita una máquina
Windows real.
