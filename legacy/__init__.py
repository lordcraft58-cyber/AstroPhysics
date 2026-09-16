"""Código heredado (pre-Fase 6), mantenido como paquete importable para que
`astrophysics_suite/` pueda apoyarse en él durante la migración (patrón
strangler fig: los motores nuevos delegan en la implementación heredada ya
probada mientras se extraen función por función, en vez de reimplementar
todo de golpe -- ver docs/audit/07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md).

Nada fuera de `astrophysics_suite/` debería depender de `legacy/` a largo
plazo; esta dependencia se elimina módulo a módulo según avanza la Fase 6.
"""
