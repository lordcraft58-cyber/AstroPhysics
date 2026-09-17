"""Contrato central del motor de informes: `ScientificResult` -- una
`ReportSection` por bloque temático (calidad, astrometría, fotometría...),
cada una con campos clave/valor, tablas (`tables.table.Table`, ya
existente) y series (`DataSeries`, listas para graficar). Deliberadamente
NO reemplaza los tipos ya tipados de cada motor (`Candidate`,
`AnomalyVector`...) -- es una VISTA construida a partir de ellos, igual
que `Table` ya lo es de las mediciones de cada motor.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.tables.table import Table


@dataclass(frozen=True)
class DataSeries:
    """Una serie real lista para graficar -- SIEMPRE construida a partir
    de puntos ya medidos por un motor (nunca interpolados ni inventados
    para que la gráfica "se vea mejor"). `y_error` es opcional pero,
    cuando existe, tiene la misma longitud que `y`."""

    name: str
    x: tuple[float, ...]
    y: tuple[float, ...]
    x_label: str
    y_label: str
    x_unit: str = ""
    y_unit: str = ""
    y_error: tuple[float, ...] | None = None
    kind: str = "line"
    """"line" (serie continua, p. ej. curva de luz), "scatter" (puntos
    independientes, p. ej. trayectoria RA/Dec) o "bar" (categórica, p. ej.
    las siete dimensiones de anomalía) -- decide cómo se dibuja, nunca
    cambia los datos."""
    x_categories: tuple[str, ...] | None = None
    """Solo para `kind="bar"`: la etiqueta real de cada posición de `x`
    (p. ej. los nombres de las dimensiones de anomalía) -- `x` sigue
    siendo `0..n-1` para mantener el mismo contrato numérico que el
    resto de series."""

    def __post_init__(self) -> None:
        if len(self.x) != len(self.y):
            raise ValueError(f"x ({len(self.x)}) y y ({len(self.y)}) deben tener la misma longitud")
        if self.y_error is not None and len(self.y_error) != len(self.y):
            raise ValueError("y_error debe tener la misma longitud que y")
        if self.x_categories is not None and len(self.x_categories) != len(self.x):
            raise ValueError("x_categories debe tener la misma longitud que x")


@dataclass(frozen=True)
class ReportField:
    """Una fila real de "clave: valor" dentro de una sección -- el mismo
    contenido que ya muestra `candidate_detail_widget.py`, formalizado
    como dato en vez de solo texto de interfaz."""

    label: str
    value: str
    available: bool = True


@dataclass(frozen=True)
class ReportSection:
    key: str
    """Identificador estable (p. ej. "quality", "astrometry") -- lo que
    usan las plantillas de exportación para decidir el orden/formato,
    nunca traducido."""
    title: str
    """Título legible en español, el que se muestra de verdad."""
    fields: tuple[ReportField, ...] = ()
    tables: tuple[Table, ...] = ()
    series: tuple[DataSeries, ...] = ()
    notes: tuple[str, ...] = ()


@dataclass(frozen=True)
class ScientificResult:
    """`FITS -> medición -> incertidumbre -> ... -> informe`: el
    resultado final de esa cadena para UN sujeto (un `Candidate` hoy;
    el contrato no asume que sea el único motor que produzca uno).
    `sections` respeta el orden en que se añadieron -- el llamador
    decide el orden real, nunca se reordena aquí."""

    schema_version: int
    subject_id: str
    title: str
    generated_at: datetime
    provenance: Provenance
    """Procedencia de la GENERACIÓN de este informe (versión de
    pipeline, motor `reporting.candidate_report`) -- distinta de la
    procedencia de cada motor que produjo los datos que resume, que
    sigue viajando dentro de cada sección real."""
    sections: tuple[ReportSection, ...] = field(default_factory=tuple)

    def section(self, key: str) -> ReportSection | None:
        return next((s for s in self.sections if s.key == key), None)

    def to_dict(self) -> dict[str, Any]:
        """Vista ligera para depuración/pruebas -- no es el contrato de
        persistencia (eso es `io.session_export`, que persiste el
        `Candidate` real, la fuente de verdad; este informe se
        regenera de él, no se recarga desde disco)."""
        return {
            "schema_version": self.schema_version,
            "subject_id": self.subject_id,
            "title": self.title,
            "generated_at": self.generated_at.isoformat(),
            "provenance": self.provenance.to_dict(),
            "sections": [
                {
                    "key": s.key,
                    "title": s.title,
                    "fields": [{"label": f.label, "value": f.value, "available": f.available} for f in s.fields],
                    "n_tables": len(s.tables),
                    "n_series": len(s.series),
                    "notes": list(s.notes),
                }
                for s in self.sections
            ],
        }
