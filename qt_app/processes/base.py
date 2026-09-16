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


@dataclass(frozen=True)
class ParameterSpec:
    name: str
    label: str
    kind: str
    """"float", "int" o "bool"."""
    default: Any
    minimum: float | int | None = None
    maximum: float | int | None = None
    decimals: int = 3
    help_text: str = ""

    def __post_init__(self) -> None:
        if self.kind not in ("float", "int", "bool"):
            raise ValueError(f"kind debe ser 'float', 'int' o 'bool'; recibido {self.kind!r}")


@dataclass(frozen=True)
class ProcessResult:
    output_data: np.ndarray | None
    """Nueva imagen resultante, o `None` si el proceso solo mide/informa
    (p. ej. fotometría) sin producir una imagen nueva."""
    summary: str
    log_lines: tuple[str, ...] = ()


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

    @property
    def is_wired(self) -> bool:
        return self.run is not None
