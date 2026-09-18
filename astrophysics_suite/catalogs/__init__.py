"""Identification Engine (Fase 6, continuación): cruce con Gaia.

La lógica de emparejamiento (`classify_against_gaia_neighbors`) es una
función pura, testeable sin red. La consulta real a Gaia
(`query_gaia_neighbors`) delega en `legacy...crossmatch_gaia_safe()` y
requiere red -- en este entorno de desarrollo el host de Gaia no está en
la lista de permitidos del proxy de red, así que solo se pudo verificar
end-to-end la parte pura; la consulta real queda cubierta por un test que
se salta explícitamente si la red no está disponible. Unifica, a
propósito, el único cliente Gaia que este paquete usará -- el código
heredado tenía dos (`query_gaia_sources` y `crossmatch_gaia_safe`) con
formatos de retorno distintos (ver docs/audit/05-..., seccion 7 nota 3).
"""
