"""Discovery Engine: orquesta los motores extraídos en la Fase 6 en una
única ruta real `Observation -> list[Candidate]`.

Fase 7 (ver docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 6, y
docs/audit/09-FASE7-DISCOVERY-ENGINE.md). Cubre el "modo genérico"
(equivalente al antiguo Discovery Workspace v57: cualquier imagen,
detección agnóstica de tipo de objeto) de principio a fin. El "modo
especializado" (choque OIII/Hα, con física/anomalía/evidencia completas)
se demuestra integrado -- physics + anomaly + evidence trabajando juntos
sobre una fila de observables -- pero todavía no está conectado a
detección real de imagen, porque eso requiere extraer la parte de
`analyze_pair_core` que mide los observables físicos desde los píxeles
(perfiles, ratios de línea), un trabajo de extracción mucho mayor que
queda fuera de esta fase.
"""
