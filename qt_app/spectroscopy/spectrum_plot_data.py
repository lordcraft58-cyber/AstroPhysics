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
    x_unit: str = ""
    """Unidad real del eje X cuando es una longitud de onda -- `"Å"` si
    el proceso de origen ya calibró de verdad, `""` en cualquier otro
    caso (píxel sin calibrar, o cualquier eje que no sea una longitud de
    onda) -- nunca se ofrece un selector de unidades donde no hay una
    unidad física real que convertir (§15)."""


WAVELENGTH_UNITS: tuple[str, ...] = ("Å", "nm", "μm")
"""Unidades reales soportadas por el selector del visor (§15), en el
orden en que se muestran."""

_WAVELENGTH_UNIT_FACTORS: dict[str, float] = {"Å": 1.0, "nm": 0.1, "μm": 1.0e-4}
"""Factor multiplicativo real desde Å -- conversión de unidades pura
(1 Å = 0.1 nm = 1e-4 μm), no una física distinta."""

_WAVELENGTH_UNIT_LABELS: dict[str, str] = {"Å": "Longitud de onda (Å)", "nm": "Longitud de onda (nm)", "μm": "Longitud de onda (μm)"}


def convert_wavelength_plot_data(plot_data: SpectrumPlotData, to_unit: str) -> SpectrumPlotData:
    """Nuevo `SpectrumPlotData` con el eje X real convertido de la unidad
    ya declarada en `plot_data.x_unit` a `to_unit` (§15: selector Å/nm/μm) --
    solo válido cuando `plot_data.x_unit` es una de las unidades de
    longitud de onda reales conocidas; nunca se llama sobre un eje de
    píxel (no hay ninguna unidad física que convertir ahí)."""
    if not plot_data.x_unit:
        raise ValueError("plot_data.x_unit está vacío -- este eje no es una longitud de onda real, no hay unidad que convertir")
    if plot_data.x_unit not in _WAVELENGTH_UNIT_FACTORS or to_unit not in _WAVELENGTH_UNIT_FACTORS:
        raise ValueError(f"unidad desconocida: {plot_data.x_unit!r} -> {to_unit!r} (válidas: {sorted(_WAVELENGTH_UNIT_FACTORS)})")
    if plot_data.x_unit == to_unit:
        return plot_data
    # Å como unidad intermedia: dato_en_angstrom = x / factor(unidad_actual); x_nuevo = dato_en_angstrom * factor(unidad_nueva)
    scale = _WAVELENGTH_UNIT_FACTORS[to_unit] / _WAVELENGTH_UNIT_FACTORS[plot_data.x_unit]
    new_series = tuple(
        SpectrumSeries(label=s.label, x=s.x * scale, y=s.y, color=s.color, style=s.style, y_error=s.y_error)
        for s in plot_data.series
    )
    new_markers = tuple(
        SpectrumMarker(x_start=m.x_start * scale, x_end=m.x_end * scale, label=m.label, color=m.color)
        for m in plot_data.markers
    )
    return SpectrumPlotData(
        series=new_series, x_label=_WAVELENGTH_UNIT_LABELS[to_unit], y_label=plot_data.y_label,
        markers=new_markers, x_unit=to_unit,
    )


def wavelength_to_angstrom(value: float, unit: str) -> float:
    """`value` (en `unit`, una de `WAVELENGTH_UNITS`) convertido a Å --
    p. ej. para buscar líneas de catálogo (siempre en Å, §10) a partir de
    una posición real leída del visor en la unidad que esté mostrando en
    ese momento (§15)."""
    if unit not in _WAVELENGTH_UNIT_FACTORS:
        raise ValueError(f"unidad desconocida: {unit!r} (válidas: {sorted(_WAVELENGTH_UNIT_FACTORS)})")
    return value / _WAVELENGTH_UNIT_FACTORS[unit]


def angstrom_to_wavelength_unit(value_angstrom: float, unit: str) -> float:
    """Inversa de `wavelength_to_angstrom` -- un valor real en Å (p. ej.
    la longitud de onda de catálogo de una línea, §10) convertido a la
    unidad que el visor esté mostrando en ese momento, para dibujar una
    marca en el sitio correcto sin importar la unidad activa."""
    if unit not in _WAVELENGTH_UNIT_FACTORS:
        raise ValueError(f"unidad desconocida: {unit!r} (válidas: {sorted(_WAVELENGTH_UNIT_FACTORS)})")
    return value_angstrom * _WAVELENGTH_UNIT_FACTORS[unit]


_SERIES_PALETTE: tuple[str, ...] = (DARK.accent, DARK.cyan, DARK.amber, DARK.coral, DARK.indigo)


def series_color(index: int) -> str:
    """Color real del ciclo de paleta del tema (`qt_app.theme`, también
    sin ningún import de Qt -- son solo cadenas hexadecimales) para la
    serie `index` -- usado al construir varias series superpuestas
    (p. ej. una por apertura en `spectroscopy.multiaperture`)."""
    return _SERIES_PALETTE[index % len(_SERIES_PALETTE)]
