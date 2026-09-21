"""Contrato uniforme proceso<->GUI -- cada entrada del explorador de
procesos es un `ProcessDefinition`: metadatos para mostrarlo, la lista
de parámetros para construir su formulario, y una función `run` pura
(numpy adentro, numpy/resumen afuera) que llama a la función científica
real de `astrophysics_suite.*`. Esta capa NUNCA reimplementa algoritmos
-- solo adapta parámetros y resultados entre la GUI y la ciencia (misma
disciplina que ya regía `gui/app.py` en la Fase 8).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np

from astrophysics_suite.tables.table import Table


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    label: str
    kind: str
    """"float", "int", "bool", "choice" (una de varias opciones fijas, en
    `choices`) o "text" (texto libre corto -- p. ej. una lista de
    regiones "lo-hi,lo-hi" que el propio motor parsea e interpreta, no
    un tipo numérico/fijo más)."""
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    decimals: int = 3
    help_text: str = ""
    choices: tuple[str, ...] = ()
    """Opciones válidas cuando `kind == "choice"` -- la GUI las muestra
    como desplegable. Vacío para cualquier otro tipo."""

    def __post_init__(self) -> None:
        if self.kind not in ("float", "int", "bool", "choice", "text"):
            raise ValueError(f"kind debe ser 'float', 'int', 'bool', 'choice' o 'text'; recibido {self.kind!r}")
        if self.kind == "choice":
            if not self.choices:
                raise ValueError(f"el parámetro {self.name!r} es de tipo 'choice' pero no declara ninguna opción en `choices`")
            if self.default not in self.choices:
                raise ValueError(f"el valor por defecto {self.default!r} de {self.name!r} no está entre sus opciones {self.choices}")
        elif self.choices:
            raise ValueError(f"el parámetro {self.name!r} declara `choices` pero su tipo es {self.kind!r}, no 'choice'")


@dataclass(frozen=True)
class ProcessResult:
    output_data: np.ndarray | None
    """Nueva imagen resultante, o `None` si el proceso solo mide/informa
    (p. ej. fotometría) sin producir una imagen nueva."""
    summary: str
    log_lines: tuple[str, ...] = ()
    table: Table | None = None
    """Tabla con una fila por medición (p. ej. una por estrella), lista
    para exportar a CSV -- `None` si el proceso no produce datos
    tabulares (la mayoría no lo hacen)."""
    artifacts: dict[str, Any] = field(default_factory=dict)
    """Resultados con nombre que un proceso concreto quiera exponer más
    allá de `output_data`/`table` (p. ej. `"zeropoint_fit"` con el
    `ZeropointFit` real de `photometry.zeropoint`, para que la GUI lo
    recuerde en `SessionState` sin ensanchar este contrato genérico con
    un campo por proceso). La mayoría de los procesos lo dejan vacío."""


@dataclass(frozen=True)
class ProcessDefinition:
    process_id: str
    name: str
    category: str
    description: str
    parameters: tuple[ParameterSpec, ...] = field(default_factory=tuple)
    run: Callable[[np.ndarray, dict[str, Any]], ProcessResult] | None = None
    """`None` marca un proceso listado (para mostrar la cobertura
    completa de IRAF en el explorador) pero todavía no cableado a una
    función real en esta oleada -- ver docs/audit/11-FASE9-... El
    explorador debe distinguir esto visualmente, nunca simular un
    resultado falso para una entrada sin `run`."""
    requires_picking: int | None = None
    """`None`: `run` se ejecuta directamente sobre la imagen activa al
    pulsar "Aplicar". Un entero >= 1: antes de ejecutar, el usuario debe
    marcar exactamente ese número de posiciones sobre la imagen (clic
    izquierdo marca, clic derecho termina antes de tiempo). `0`: número
    ilimitado de posiciones (clic derecho para terminar) -- p. ej. varias
    estrellas para un ajuste de PSF simultáneo. Los puntos marcados
    llegan a `run` en `params["_picked_points"]`."""

    @property
    def is_wired(self) -> bool:
        return self.run is not None
