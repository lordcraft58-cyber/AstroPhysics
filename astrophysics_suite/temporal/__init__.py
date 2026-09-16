"""Temporal Engine, primer corte (Fase 6, continuación).

Envuelve `legacy...TemporalChangeEngine` (variabilidad/deriva en medidas
multiepoch con errores explícitos, vía chi² constante vs. ajuste lineal
ponderado). No cubre movimiento propio (`measure_proper_motion`, ya
probado desde la Fase 3 -- ver `tests/regression/test_historical_
contracts.py`) ni aparición/desaparición (que requieren comparar
detecciones presentes/ausentes entre épocas, no una serie de valores
continua) -- quedan para un slice posterior. Ver
docs/audit/08-FASE6-MOTORES-RESTANTES.md, seccion 6.
"""
