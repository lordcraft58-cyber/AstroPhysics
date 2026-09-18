"""Detection Engine (Fase 6, slice 1).

Ver docs/audit/07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md. Delega el
algoritmo de detección (DAOStarFinder vía `legacy...detect_point_sources`)
y la medición de forma por fuente (`legacy...enrich_star_rows`, momentos
de segundo orden reales) en el código heredado ya probado -- lo nuevo es
la traducción a `Detection`/`SkyPosition`/`MorphologySummary` (Fase 4).
"""
