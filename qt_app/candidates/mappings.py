"""Vocabulario -> color semántico, para la revisión de candidatos en el
taller Qt -- la misma lógica centralizada que `gui/theme.py` usaba en la
Fase 8 (Tkinter), traducida a los nombres de `qt_app.theme.Palette`. Un
único lugar: si el vocabulario de `IdentificationState` cambia, solo hay
que tocar aquí.
"""
from __future__ import annotations

STATE_COLOR_ATTR = {
    "KNOWN": "cyan",
    "KNOWN_VARIANT": "cyan",
    "UNMATCHED": "amber",
    "ANOMALOUS": "coral",
    "TRANSIENT_CANDIDATE": "coral",
    "MOVING_SOURCE_CANDIDATE": "indigo",
    "DISCOVERY_REVIEW": "amber",
}
STATE_LABEL_ES = {
    "KNOWN": "Conocido",
    "KNOWN_VARIANT": "Conocido (variante)",
    "UNMATCHED": "No asociado",
    "ANOMALOUS": "Anomalía",
    "TRANSIENT_CANDIDATE": "Transitorio",
    "MOVING_SOURCE_CANDIDATE": "Movimiento",
    "DISCOVERY_REVIEW": "Requiere revisión",
}

REVIEW_COLOR_ATTR = {"PENDING": "ink_faint", "KEPT": "cyan", "REJECTED": "coral", "FLAGGED": "amber"}
REVIEW_LABEL_ES = {"PENDING": "Pendiente", "KEPT": "Conservado", "REJECTED": "Descartado", "FLAGGED": "Marcado"}
