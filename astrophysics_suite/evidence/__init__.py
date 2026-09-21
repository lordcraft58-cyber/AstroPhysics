"""Evidence Engine, primer corte (Fase 6, continuación) -- el núcleo
conceptual del producto (ver el encargo original).

Envuelve `legacy...DiscoveryEvidenceEngine.evaluate_rows()`, que ya
implementa el principio correcto de independencia de evidencias
(`independent_evidence_count`, `priority_index` desmontable, revisión
humana siempre obligatoria -- ver docs/audit/01-..., seccion 13.2). Lo
nuevo aquí es traducir sus cuatro señales internas (tensión física,
anomalía de referencia, discrepancia de modelo, novedad visual) a
`EvidenceItem` explícitos por motor de origen, de forma que
`EvidenceChain.independent_evidence_count` (Fase 4, una propiedad
calculada, no un campo que se pueda falsear) reproduzca exactamente el
mismo conteo que el motor heredado ya calculaba -- confirmando que el
diseño de la Fase 4 generaliza correctamente la idea original.
"""
