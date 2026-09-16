"""Artifact Rejection Engine (Fase 6, continuación).

Envuelve `legacy...._label_discovery_morphology()`. Es deliberadamente
estrecho: esa función solo distingue elongación/compacidad/S-N extremos,
NO clasifica entre las 13 categorías de `ArtifactKind` (hot pixel, rayo
cósmico, saturación, reflejo, gradiente, donut, ...) porque el código
heredado no tiene lógica real para la mayoría de ellas -- inventar esa
clasificación sin una base científica validada violaría el principio
central de esta reingeniería. Ver docs/audit/08-FASE6-MOTORES-RESTANTES.md.
"""
