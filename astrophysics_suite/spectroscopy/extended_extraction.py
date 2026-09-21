"""Extracción de objetos extendidos (§27) -- nebulosas, galaxias u otra
emisión difusa que puede llenar gran parte de la rendija, sin asumir
nunca un perfil espacial de fuente puntual.

`trace_spectrum` sigue un centroide columna a columna -- razonable
incluso para emisión extendida si tiene una forma espacial simétrica
clara, pero `extract_optimal` (Horne 1986) va más allá: asume que TODAS
las columnas comparten un único perfil espacial normalizado a un pico
(`master_profile`), una premisa que no se sostiene para emisión difusa
real que puede ser plana, multi-pico o variar de forma a lo largo de la
rendija -- usarla ahí produciría una extracción sesgada sin ningún aviso.
Por eso este módulo reutiliza SIEMPRE `extract_sum` (suma simple,
sin pesos por perfil) sobre una región espacial que el llamador define
directamente -- nunca detectada por un pico de brillo, y nunca por
`extract_optimal`.

Reutiliza `trace_spectrum`/`extract_sum`/`estimate_sky_background` ya
probados (Fase 9.5) -- solo cambia cómo se construye la traza de entrada:
una `TraceResult` sintética de centro CONSTANTE (el centro de la región
dada), en vez de un centroide columna a columna. Misma disciplina de "no
medir nada por una segunda vía" que ya rige `multiaperture.py`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.trace import (
    DEFAULT_SKY_WINDOWS,
    ExtractedSpectrum,
    SkyWindow,
    TraceResult,
    extract_sum,
)


@dataclass(frozen=True)
class SpatialRegion:
    row_start: float
    """Primera fila incluida en la región (rango CERRADO por ambos
    extremos -- `row_start` Y `row_end` se incluyen los dos, igual
    convención que "de la fila X a la fila Y" en la GUI; NO es un rango
    estilo `data[row_start:row_end]` de Python, que excluiría `row_end`).
    """
    row_end: float
    """Última fila incluida en la región (inclusive)."""
    label: str = ""

    def __post_init__(self) -> None:
        if self.row_end < self.row_start:
            raise ValueError("row_end debe ser >= row_start")

    @property
    def center_px(self) -> float:
        return (self.row_start + self.row_end) / 2.0

    @property
    def half_width_px(self) -> float:
        return (self.row_end - self.row_start) / 2.0


def _region_to_constant_trace(n_columns: int, region: SpatialRegion) -> TraceResult:
    """Traza SINTÉTICA de centro constante -- la región la define el
    llamador directamente, no se sigue ningún centroide columna a
    columna. `fit_degree=0`/`rms_residual_px=0.0` documentan que no hubo
    ningún ajuste real, solo una región fija."""
    columns = np.arange(n_columns, dtype=np.float64)
    center_px = np.full(n_columns, region.center_px, dtype=np.float64)
    return TraceResult(
        columns=columns, center_px=center_px, fit_degree=0, rms_residual_px=0.0, n_columns_used_for_fit=n_columns,
    )


def _validate_sky_windows_do_not_overlap_region(region: SpatialRegion, sky_windows: tuple[SkyWindow, ...]) -> None:
    """Una región de objeto extendido puede ser mucho más ancha que
    `DEFAULT_SKY_WINDOWS` (±10 px) -- si una ventana de cielo cae DENTRO
    de la propia región, el "cielo" medido incluiría flujo real del
    objeto, sesgando la resta de fondo sin ningún aviso. Se rechaza
    explícitamente en vez de dejarlo pasar en silencio."""
    for window in sky_windows:
        sky_lo = window.offset_px - window.half_width_px
        sky_hi = window.offset_px + window.half_width_px
        if sky_lo < region.half_width_px and sky_hi > -region.half_width_px:
            raise ValueError(
                f"la ventana de cielo (offset={window.offset_px}, semiancho={window.half_width_px}) "
                f"solapa la región del objeto extendido (semiancho={region.half_width_px}) -- "
                "elige ventanas de cielo fuera de la región (y, si el objeto llena buena parte de la rendija, "
                "fuera de su extensión real completa, no solo de esta región)."
            )


def extract_extended_region(
    data: np.ndarray,
    uncertainty: np.ndarray,
    region: SpatialRegion,
    *,
    mask: np.ndarray | None = None,
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    sky_reducer: str = "median",
    min_valid_fraction: float = 0.3,
) -> ExtractedSpectrum:
    """Extrae por suma simple (boxcar) el flujo real de `region` --
    NUNCA por extracción óptima (ver docstring del módulo).

    Se valida que ninguna ventana de `sky_windows` solape la región misma
    antes de restar cielo. Un `sky_windows=()` NO es una forma de "omitir
    la resta de cielo": igual que en `extract_sum`/`estimate_sky_
    background`, sin evidencia real de cielo la columna entera queda
    inválida (`NaN`) -- restar un cielo de `0.0` inventado sería peor que
    no medir nada. Si el objeto llena tanto la rendija que no queda cielo
    limpio en ningún lado, este motor no puede inventarlo: hace falta una
    exposición de cielo separada."""
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    height = data.shape[0]
    if region.row_start < 0 or region.row_end > height - 1:
        raise ValueError(
            f"la región [{region.row_start}, {region.row_end}] cae fuera de la imagen "
            f"(filas válidas: [0, {height - 1}])"
        )
    if sky_windows:
        _validate_sky_windows_do_not_overlap_region(region, sky_windows)
    trace = _region_to_constant_trace(data.shape[1], region)
    return extract_sum(
        data, uncertainty, trace, mask=mask, aperture_half_width=region.half_width_px,
        sky_windows=sky_windows, sky_reducer=sky_reducer, min_valid_fraction=min_valid_fraction,
    )


@dataclass(frozen=True)
class RegionExtraction:
    region: SpatialRegion
    spectrum: ExtractedSpectrum


@dataclass(frozen=True)
class RegionExtractionFailure:
    region: SpatialRegion
    reason: str


@dataclass(frozen=True)
class MultiRegionResult:
    extractions: list[RegionExtraction]
    """Una por cada región que sí se pudo extraer, en el mismo orden que
    `regions`."""
    failures: list[RegionExtractionFailure]
    """Una por cada región que falló, con el motivo real -- nunca se
    omite en silencio ni detiene el resto del lote."""


def extract_multi_region(
    data: np.ndarray,
    uncertainty: np.ndarray,
    regions: list[SpatialRegion],
    *,
    mask: np.ndarray | None = None,
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    sky_reducer: str = "median",
    min_valid_fraction: float = 0.3,
) -> MultiRegionResult:
    """Extrae cada región de `regions` por separado -- útil para
    resolver espacialmente un objeto extendido a lo largo de la rendija
    (p. ej. núcleo vs. borde de una nebulosa, o varios bins espaciales
    para un perfil posición-velocidad), sin asumir en ningún caso un
    perfil de fuente puntual."""
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")

    extractions: list[RegionExtraction] = []
    failures: list[RegionExtractionFailure] = []
    for region in regions:
        try:
            spectrum = extract_extended_region(
                data, uncertainty, region, mask=mask, sky_windows=sky_windows,
                sky_reducer=sky_reducer, min_valid_fraction=min_valid_fraction,
            )
        except ValueError as exc:
            failures.append(RegionExtractionFailure(region=region, reason=str(exc)))
            continue
        extractions.append(RegionExtraction(region=region, spectrum=spectrum))

    return MultiRegionResult(extractions=extractions, failures=failures)
