"""Capa de servicios: lo único autorizado a mediar entre `gui/` y los
motores de `astrophysics_suite/` (ver docs/audit/02-ARQUITECTURA-OBJETIVO-
Y-PLAN.md, seccion 3.2, y docs/audit/10-FASE8-GUI.md).

Responsabilidades: ejecutar trabajo pesado fuera del hilo de la GUI con
progreso y cancelación segura, mantener el estado de sesión (proyecto en
memoria), y puentear el `logging` de los motores hacia la interfaz.
Ningún módulo de este paquete importa `tkinter`; `gui/` es el único
paquete que puede depender de él.
"""
