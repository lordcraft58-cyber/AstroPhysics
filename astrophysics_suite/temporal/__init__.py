"""Temporal Engine.

Variabilidad/deriva en medidas multiépoca con errores explícitos, vía
chi² constante vs. ajuste lineal ponderado (nativo desde el cierre
sistemático del motor 9/16, informe 97 -- antes delegaba en
`legacy...TemporalChangeEngine`). Movimiento propio real vía
`temporal/motion.py`. Ver docs/audit/08-FASE6-MOTORES-RESTANTES.md,
seccion 6, y docs/audit/97-AUDITORIA-SISTEMATICA-MOTOR-09-TEMPORAL.md.
"""
