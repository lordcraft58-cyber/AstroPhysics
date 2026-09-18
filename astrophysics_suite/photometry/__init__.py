"""Characterization Engine, primer corte (Fase 6, continuación).

Envuelve `legacy...measure_source_quality()` -- medición por fuente vía
momentos 2D reales, independiente de `enrich_star_rows` (usada en
`detection/`). Nota de diseño detectada durante la extracción: ambas
funciones calculan FWHM/elipticidad con fórmulas de momentos ligeramente
distintas para etapas de pipeline distintas -- es el mismo patrón de
"misma medición, dos implementaciones" que motivó esta reingeniería,
documentado aquí en vez de ignorado (ver
docs/audit/08-FASE6-MOTORES-RESTANTES.md, seccion 3).

Deliberadamente NO cubre calibración fotométrica absoluta ni perfiles
radiales todavía -- necesitan zeropoint/exposición/ganancia y un centro
definido que `Observation`/`Detection` no cargan hoy; es trabajo de un
slice posterior.
"""
