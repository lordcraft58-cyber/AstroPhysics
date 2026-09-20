"""Contrato de datos puro para el overlay de traza/apertura/cielo sobre
la imagen 2D (`qt_app.mdi.image_window.ImageView.set_trace_overlay`) --
deliberadamente SIN ningún import de PySide6, mismo motivo que
`spectrum_plot_data.py`: `qt_app/processes/registry.py` (que construye
estos objetos) debe seguir siendo "numpy puro, comprobable sin Qt".

Cierra el hueco más repetido del encargo de 43 secciones (§2, §3, §5,
§28): hasta ahora, trazar/extraer un espectro era una caja negra -- un
clic, y el resultado aparecía en una ventana 1D nueva, sin ver nunca
sobre la imagen 2D real qué traza, qué límites de apertura y qué
regiones de cielo se usaron de verdad.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.trace import SkyWindow


@dataclass(frozen=True)
class TraceOverlay:
    trace_columns: np.ndarray
    """Columnas (eje de dispersión) reales cubiertas por la traza."""
    trace_center_px: np.ndarray
    """Centro espacial REAL en cada columna -- `trace.center_px` de
    `trace_spectrum`, o el centro constante de una región fija
    (`extended_extraction`), nunca una fila supuesta."""
    aperture_half_width: float
    sky_windows: tuple[SkyWindow, ...] = ()
    label: str = ""
