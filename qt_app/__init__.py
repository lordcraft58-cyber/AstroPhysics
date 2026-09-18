"""Taller de procesamiento estilo PixInsight (PySide6/Qt) -- sustituye a
la GUI en Tkinter de la Fase 8 (ver docs/audit/10-FASE8-GUI.md y
docs/audit/11-FASE9-IRAF-PIXINSIGHT-PLAN.md). Único paquete con permiso
de importar Qt; `astrophysics_suite/` (ciencia) y `services/` no lo
importan nunca -- la dirección de dependencia establecida desde la
Fase 4 se mantiene: `astrophysics_suite/` <- `services/` <- `qt_app/`.
"""
