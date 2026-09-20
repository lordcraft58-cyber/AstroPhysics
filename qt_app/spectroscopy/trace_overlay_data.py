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
from typing import Callable

import numpy as np

from astrophysics_suite.spectroscopy.trace import DEFAULT_SKY_WINDOWS, ExtractedSpectrum, SkyWindow, TraceResult


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


@dataclass(frozen=True)
class TraceEditContext:
    """Todo lo necesario para volver a extraer la MISMA traza ya
    calculada con una apertura distinta, sin repetir el trazado ni pedir
    un nuevo clic (§2): capturado por el proceso que produjo la traza
    (`spectroscopy.trace`/`spectroscopy.autoprocess`, ver `registry.py`)
    y reutilizado por `recalculate_extraction` cuando el usuario arrastra
    el borde de la apertura sobre el overlay real en `ImageView`.

    Solo para el caso de UNA traza (no multi-apertura/objeto extendido,
    que producen varias trazas independientes a la vez -- editar varias
    aperturas simultáneas queda fuera de este slice)."""

    trace: TraceResult
    data: np.ndarray
    uncertainty: np.ndarray
    mask: np.ndarray | None
    extractor: Callable[..., ExtractedSpectrum]
    extraction_method_label: str
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS
    sky_smooth_degree: int | None = None
    sky_smooth_sigma_clip: float = 3.0


def recalculate_extraction(context: TraceEditContext, new_aperture_half_width: float) -> ExtractedSpectrum:
    """Reextrae con la traza YA calculada de `context` y el nuevo
    semiancho de apertura real -- ni la traza ni el cielo se recalculan
    desde cero, exactamente el mismo motor que ya usó el proceso
    original (`context.extractor`), solo con `aperture_half_width`
    distinto (§2: "recalcular" tras editar la apertura a mano)."""
    if not (new_aperture_half_width > 0):
        raise ValueError(f"el semiancho de apertura debe ser positivo, recibido {new_aperture_half_width:g} px")
    return context.extractor(
        context.data, context.uncertainty, context.trace,
        mask=context.mask, aperture_half_width=new_aperture_half_width,
        sky_windows=context.sky_windows, sky_smooth_degree=context.sky_smooth_degree,
        sky_smooth_sigma_clip=context.sky_smooth_sigma_clip,
    )
