"""Detection Engine.

Detección de fuentes puntuales real (DAOStarFinder vía `finder.py`, con
reserva propia en Python puro) y medición de forma por fuente
(`finder.enrich_detections`, momentos de segundo orden reales) --
migrado por completo del monolito legado (docs/audit/54-CIERRE-DETECTION.md).
`point_sources.py` traduce el resultado a `Detection`/`SkyPosition`/
`MorphologySummary` (Fase 4).
"""
