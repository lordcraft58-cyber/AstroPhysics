"""Anomaly Engine, primer corte (Fase 6, continuación): dimensión física.

Envuelve `legacy...PhysicalConstraintEngine` (tensiones internas entre
parámetros relacionados por física básica, p. ej. edad vs. radio/
velocidad) y `legacy...build_reference_anomaly` (comparación contra una
referencia externa declarada) para poblar `AnomalyVector.physical`.

Las demás dimensiones (`photometric`, `morphological`, `spectral`,
`temporal`, `astrometric`, `spatial`) quedan fuera de este corte:
`spatial` requiere `SpatialTrendAnomalyEngine` operando sobre una
*población* de detecciones a la vez (no una sola, como el resto de este
paquete), y las demás no tienen todavía una fuente de datos poblada por
los motores ya extraídos. Ver docs/audit/08-FASE6-MOTORES-RESTANTES.md,
seccion 5.
"""
