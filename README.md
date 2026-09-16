# AstroPhysics Suite

Estación de descubrimiento astrofísico asistida por ordenador. Analiza observaciones astronómicas reales para detectar fuentes y estructuras, identificarlas contra catálogos, caracterizarlas, detectar anomalías y cambios temporales, y generar **candidatos científicos auditables para revisión humana** — nunca descubrimientos automáticos.

Filosofía central: **IMÁGENES → DETECCIÓN → IDENTIFICACIÓN → CARACTERIZACIÓN → COMPARACIÓN → ANOMALÍAS → EVIDENCIAS → CANDIDATO CIENTÍFICO → REVISIÓN HUMANA**.

## Estado del proyecto

En reingeniería activa. El código heredado (`legacy/AstroPhysicsSuite_v57_3_COMMERCIAL.py`, ~14.300 líneas) contiene rigor científico acumulado a lo largo de muchas iteraciones, pero también fragmentación arquitectónica significativa. La Fase 1 (auditoría completa) ya se ha realizado:

- [`docs/audit/01-AUDITORIA-TECNICA-FASE1.md`](docs/audit/01-AUDITORIA-TECNICA-FASE1.md) — inventario completo, duplicados, código muerto, funciones monolíticas, hallazgos de seguridad/rendimiento/testing, y el hallazgo central: tres pipelines de "descubrimiento" paralelos y no interoperables.
- [`docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md`](docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md) — arquitectura de paquetes objetivo, contratos de los motores especializados (Detection, Artifact Rejection, Identification, Characterization, Temporal, Physical, Anomaly, Discovery AI, Evidence, Candidate), GUI comercial objetivo, y plan de migración por fases.
- [`docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md`](docs/audit/03-MAPEO-DEPENDENCIAS-Y-CONTRATOS.md) — Fase 2: grafo de llamadas completo, barrido de código muerto al 100% (23 de 307 entidades), cuantificación exacta de qué motores son alcanzables desde la GUI vs. solo desde la CLI (78 entidades CLI-only), y contratos reales de las funciones/clases que alimentarán cada motor objetivo.

No es un programa de astrofotografía ni compite con PixInsight/Siril en procesamiento estético. El objetivo es descubrimiento científico a partir de imágenes reales de telescopio.
