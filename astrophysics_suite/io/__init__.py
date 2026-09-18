"""Lectura de imágenes y construcción de `Observation`.

Fase 6, slice 1 (ver docs/audit/07-FASE6-REFACTOR-PROGRESIVO-SLICE1.md):
delega la lectura real de FITS en `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.
load_fits` -- probada, con manejo cuidadoso de cubos 3D/4D y WCS -- en vez
de reimplementarla. Lo nuevo aquí es la traducción a los contratos de la
Fase 4 (`ImageRef`, `Observation`), no el algoritmo de lectura FITS en sí.
"""
