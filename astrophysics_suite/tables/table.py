"""Tabla científica genérica -- equivalente propio de las capacidades de
tabla/catálogo de `astcat` de IRAF: filas + columnas nombradas con
unidad, exportables a CSV, reutilizable por cualquier motor que produzca
una lista de mediciones (fotometría, astrometría...) sin que cada uno
reinvente su propio formato de exportación.

Deliberadamente aditivo: no sustituye ni reestructura los tipos de
resultado ya existentes de cada motor (`ApertureMeasurement`,
`PSFFitResult`, `WCSSolution`...) -- esos siguen siendo el contrato real
y tipado de cada motor. `Table` es una vista de exportación que el
llamador arma explícitamente a partir de ellos, no su reemplazo;
unificar todos esos tipos bajo un contrato común queda documentado como
una brecha de arquitectura real para una fase dedicada, ver
`docs/audit/13-IRAF-CAPABILITY-MAP.md` §6.
"""
from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Table:
    columns: tuple[str, ...]
    units: tuple[str, ...]
    """Misma longitud que `columns`; cadena vacía si una columna no tiene unidad."""
    rows: tuple[tuple[Any, ...], ...]
    """Cada fila es una tupla de valores en el mismo orden que `columns`."""

    def __post_init__(self) -> None:
        if len(self.units) != len(self.columns):
            raise ValueError("units debe tener la misma longitud que columns")
        for row in self.rows:
            if len(row) != len(self.columns):
                raise ValueError(f"fila con {len(row)} valores; se esperaban {len(self.columns)} ({self.columns})")

    def to_csv(self, path: str) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", newline="", encoding="utf-8") as handle:
            writer = csv.writer(handle)
            writer.writerow(_column_header(name, unit) for name, unit in zip(self.columns, self.units))
            writer.writerows(self.rows)

    @classmethod
    def from_csv(cls, path: str) -> "Table":
        with open(path, newline="", encoding="utf-8") as handle:
            reader = csv.reader(handle)
            try:
                header = next(reader)
            except StopIteration:
                return cls(columns=(), units=(), rows=())
            columns, units = zip(*(_parse_column_header(cell) for cell in header)) if header else ((), ())
            rows = tuple(tuple(_parse_value(cell) for cell in row) for row in reader)
        return cls(columns=tuple(columns), units=tuple(units), rows=rows)


def _column_header(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _parse_column_header(cell: str) -> tuple[str, str]:
    if cell.endswith("]") and "[" in cell:
        name, _, unit = cell.rpartition("[")
        return name.strip(), unit.rstrip("]").strip()
    return cell, ""


def _parse_value(text: str) -> Any:
    try:
        return int(text)
    except ValueError:
        pass
    try:
        return float(text)
    except ValueError:
        pass
    return text
