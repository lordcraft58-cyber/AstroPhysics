"""Extracción multi-apertura -- localizar y extraer varias trazas
espectrales reales de una misma imagen 2D (varios objetos en la misma
rendija, o varias fibras) -- equivalente propio de `apall` cuando se le
dan/detectan varias aperturas en vez de una sola.

Reutiliza `trace_spectrum`/`extract_sum`/`extract_optimal` ya probados
para CADA apertura por separado -- no reimplementa el trazado ni la
extracción, solo localiza automáticamente dónde hay más de un objeto
real (o usa los centros que dé el llamador) y orquesta el motor ya
existente sobre cada uno. Misma disciplina de "no medir nada por una
segunda vía" que ya rige el resto del proyecto (ver
docs/audit/45-CIERRE-BACKLOG-PENDIENTE-MOTORES-ANTERIORES.md, sobre
`band_ratios`/agrupación cruzada).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import signal

from astrophysics_suite.spectroscopy.trace import (
    ExtractedSpectrum,
    SkyWindow,
    TraceResult,
    extract_optimal,
    extract_sum,
    trace_spectrum,
)

_MAD_TO_SIGMA = 1.4826


def find_aperture_centers(
    data: np.ndarray,
    *,
    min_snr: float = 5.0,
    min_separation_px: float = 10.0,
    max_apertures: int = 20,
) -> list[float]:
    """Detecta centros reales de apertura a partir del perfil espacial
    (mediana por fila a lo largo de todo el eje de dispersión -- robusta
    frente a una sola línea de emisión brillante o un rayo cósmico
    puntual, a diferencia de una simple suma). Un pico cuenta como
    apertura real si supera `min_snr` veces el ruido robusto (MAD) sobre
    el fondo, separado al menos `min_separation_px` de cualquier otro.
    Si hay más de `max_apertures` picos válidos, se quedan los
    `max_apertures` más brillantes -- devueltos en orden espacial
    creciente (no por brillo), el orden natural para el llamador."""
    if data.ndim != 2:
        raise ValueError("find_aperture_centers opera sobre imágenes 2D (espacial x dispersión)")

    spatial_profile = np.median(data, axis=1)
    background = float(np.median(spatial_profile))
    mad = float(np.median(np.abs(spatial_profile - background)))
    noise = max(mad * _MAD_TO_SIGMA, 1e-9)

    peak_indices, properties = signal.find_peaks(
        spatial_profile, height=background + min_snr * noise, distance=max(1, int(round(min_separation_px)))
    )
    if peak_indices.size == 0:
        return []

    heights = properties["peak_heights"]
    order = np.argsort(heights)[::-1][:max_apertures]
    selected = np.sort(peak_indices[order])
    return [float(p) for p in selected]


@dataclass(frozen=True)
class Aperture:
    aperture_id: int
    initial_center_px: float
    trace: TraceResult
    spectrum: ExtractedSpectrum


@dataclass(frozen=True)
class ApertureExtractionFailure:
    aperture_id: int
    initial_center_px: float
    reason: str


@dataclass(frozen=True)
class MultiApertureResult:
    apertures: list[Aperture]
    """Una por cada centro que sí se pudo trazar y extraer -- en el
    mismo orden espacial que los centros de entrada."""
    failures: list[ApertureExtractionFailure]
    """Una por cada centro que no se pudo trazar/extraer, con el motivo
    real -- nunca se omite en silencio ni hace fallar el resto del lote."""


def extract_multi_aperture(
    data: np.ndarray,
    uncertainty: np.ndarray,
    *,
    aperture_centers: list[float] | None = None,
    optimal_extraction: bool = True,
    fit_degree: int = 3,
    aperture_half_width: float = 4.0,
    bg_offset: float = 10.0,
    bg_half_width: float = 4.0,
    mask: np.ndarray | None = None,
    find_min_snr: float = 5.0,
    find_min_separation_px: float = 10.0,
    find_max_apertures: int = 20,
) -> MultiApertureResult:
    """Traza y extrae una apertura real por cada centro de
    `aperture_centers` (o detectados con `find_aperture_centers` si no
    se dan ninguno). Una apertura que no se puede trazar o extraer (p.
    ej. sin señal suficiente, o un centro fuera de la imagen) se reporta
    en `MultiApertureResult.failures` con el motivo real -- nunca
    detiene el lote completo ni se descarta sin decirlo."""
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")

    centers = aperture_centers if aperture_centers is not None else find_aperture_centers(
        data, min_snr=find_min_snr, min_separation_px=find_min_separation_px, max_apertures=find_max_apertures
    )

    apertures: list[Aperture] = []
    failures: list[ApertureExtractionFailure] = []
    extractor = extract_optimal if optimal_extraction else extract_sum
    # `bg_offset`/`bg_half_width` (parámetros ya existentes de la GUI) se
    # traducen a dos `SkyWindow` simétricas -- el mismo caso particular
    # que ya era el valor por defecto de `trace.estimate_sky_background`.
    sky_windows = (SkyWindow(offset_px=-bg_offset, half_width_px=bg_half_width), SkyWindow(offset_px=bg_offset, half_width_px=bg_half_width))

    for aperture_id, center in enumerate(centers, start=1):
        try:
            trace = trace_spectrum(data, initial_center_px=center, fit_degree=fit_degree, mask=mask)
            spectrum = extractor(
                data, uncertainty, trace, mask=mask,
                aperture_half_width=aperture_half_width, sky_windows=sky_windows,
            )
        except ValueError as exc:
            failures.append(ApertureExtractionFailure(aperture_id=aperture_id, initial_center_px=center, reason=str(exc)))
            continue
        apertures.append(Aperture(aperture_id=aperture_id, initial_center_px=center, trace=trace, spectrum=spectrum))

    return MultiApertureResult(apertures=apertures, failures=failures)
