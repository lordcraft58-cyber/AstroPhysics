"""Contrato de datos puro para el visor de espectros (`spectrum_view.py`)
-- deliberadamente SIN ningún import de PySide6. `qt_app/processes/
registry.py` (que construye estos objetos) debe seguir siendo "numpy
puro, comprobable sin Qt" (ver su propio docstring y
`tests/unit/qt_app/test_registry.py`, que se ejecutan en un entorno sin
PySide6 instalado) -- si este contrato viviera en el mismo módulo que el
widget `SpectrumView`, importar `SpectrumPlotData` desde `registry.py`
arrastraría PySide6 a un módulo que hoy no lo necesita para nada.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from qt_app.theme import DARK


@dataclass(frozen=True)
class SpectrumSeries:
    label: str
    x: np.ndarray
    y: np.ndarray
    color: str = "#4c78a8"
    style: str = "line"
    """"line" (trazo continuo), "dashed" (p. ej. un ajuste superpuesto al
    dato real) o "points" (marcadores sin unir)."""
    y_error: np.ndarray | None = None
    """Incertidumbre real por punto (misma forma que `y`), cuando el
    proceso que construyó esta serie ya la calculó (p. ej.
    `_uncertainty_adu`) -- `None`, nunca un valor inventado, si no hay
    incertidumbre real disponible. La usa el tooltip del visor (§29) para
    mostrar error y S/N reales bajo el cursor, además de flujo."""


@dataclass(frozen=True)
class SpectrumMarker:
    """Banda vertical resaltada -- p. ej. la ventana real usada para
    medir una línea (`LineMeasurement.window`). Puramente informativa."""
    x_start: float
    x_end: float
    label: str = ""
    color: str = "#f0b429"


@dataclass(frozen=True)
class SpectrumPlotData:
    series: tuple[SpectrumSeries, ...]
    x_label: str
    y_label: str
    markers: tuple[SpectrumMarker, ...] = ()


_SERIES_PALETTE: tuple[str, ...] = (DARK.accent, DARK.cyan, DARK.amber, DARK.coral, DARK.indigo)


def series_color(index: int) -> str:
    """Color real del ciclo de paleta del tema (`qt_app.theme`, también
    sin ningún import de Qt -- son solo cadenas hexadecimales) para la
    serie `index` -- usado al construir varias series superpuestas
    (p. ej. una por apertura en `spectroscopy.multiaperture`)."""
    return _SERIES_PALETTE[index % len(_SERIES_PALETTE)]
