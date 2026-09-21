"""AstroPhysics Suite — plataforma de descubrimiento astrofísico.

Este paquete es la arquitectura objetivo descrita en
docs/audit/02-ARQUITECTURA-OBJETIVO-Y-PLAN.md. Se construye de forma
incremental (Fase 4 en adelante) junto al monolito heredado en
``legacy/``, que sigue siendo la implementación en producción de los
motores científicos hasta que la Fase 6 los extraiga aquí.

Ningún módulo de ``astrophysics_suite`` debe importar ``tkinter`` ni
ningún otro detalle de presentación: es la capa de ciencia, ejecutable
sin GUI (ver docs/audit/02-..., seccion 3.2).
"""

__version__ = "0.4.0-dev"
