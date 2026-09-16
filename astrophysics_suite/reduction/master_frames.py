"""Construcción de fotogramas maestros de calibración -- equivalente
propio de `zerocombine`/`darkcombine`/`flatcombine` de IRAF, apoyado en
`combine.py` (sigma-clipping robusto) para el apilado.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.reduction.combine import CombineResult, combine_images


@dataclass(frozen=True)
class MasterFrame:
    data: np.ndarray
    uncertainty: np.ndarray
    n_combined: np.ndarray
    kind: str
    """"bias", "dark" o "flat"."""
    exposure_s: float | None = None
    """Tiempo de exposición de los fotogramas de entrada -- obligatorio y
    significativo para "dark" (necesario para escalar la corriente de
    oscuridad a otra exposición); ausente/irrelevante para "bias"."""
    filter_name: str = ""
    """Filtro de los fotogramas de entrada -- significativo para "flat"."""


def build_master_bias(bias_frames: list[np.ndarray], *, sigma_clip: float | None = 3.0, max_iters: int = 5) -> MasterFrame:
    if len(bias_frames) < 3:
        raise ValueError(f"build_master_bias necesita al menos 3 fotogramas para un rechazo robusto; recibidos {len(bias_frames)}")
    result = combine_images(bias_frames, method="median", sigma_clip=sigma_clip, max_iters=max_iters)
    return MasterFrame(data=result.data, uncertainty=result.uncertainty, n_combined=result.n_combined, kind="bias")


def build_master_dark(
    dark_frames: list[np.ndarray],
    *,
    exposure_s: float,
    master_bias: np.ndarray | None = None,
    sigma_clip: float | None = 3.0,
    max_iters: int = 5,
) -> MasterFrame:
    if exposure_s <= 0:
        raise ValueError("exposure_s debe ser positivo")
    if len(dark_frames) < 3:
        raise ValueError(f"build_master_dark necesita al menos 3 fotogramas para un rechazo robusto; recibidos {len(dark_frames)}")
    prepared = [frame - master_bias for frame in dark_frames] if master_bias is not None else list(dark_frames)
    result = combine_images(prepared, method="median", sigma_clip=sigma_clip, max_iters=max_iters)
    return MasterFrame(data=result.data, uncertainty=result.uncertainty, n_combined=result.n_combined, kind="dark", exposure_s=exposure_s)


def build_master_flat(
    flat_frames: list[np.ndarray],
    *,
    master_bias: np.ndarray | None = None,
    master_dark: MasterFrame | None = None,
    flat_exposure_s: float | None = None,
    filter_name: str = "",
    sigma_clip: float | None = 3.0,
    max_iters: int = 5,
) -> MasterFrame:
    """Combina y normaliza planos (de domo o de cielo) a mediana 1.0 --
    la normalización es lo que convierte el plano en un multiplicador de
    sensibilidad relativa por píxel, listo para dividir directamente una
    imagen científica calibrada (ver `calibration.py`)."""
    if len(flat_frames) < 3:
        raise ValueError(f"build_master_flat necesita al menos 3 fotogramas para un rechazo robusto; recibidos {len(flat_frames)}")

    prepared = list(flat_frames)
    if master_bias is not None:
        prepared = [frame - master_bias for frame in prepared]
    if master_dark is not None:
        if flat_exposure_s is None:
            raise ValueError("flat_exposure_s es obligatorio si se da master_dark, para escalar la corriente de oscuridad")
        scale = flat_exposure_s / master_dark.exposure_s
        prepared = [frame - master_dark.data * scale for frame in prepared]

    result: CombineResult = combine_images(prepared, method="median", sigma_clip=sigma_clip, max_iters=max_iters)
    normalization = float(np.median(result.data))
    if normalization <= 0:
        raise ValueError(f"la mediana del plano combinado no es positiva ({normalization}); no se puede normalizar")

    normalized_data = result.data / normalization
    normalized_uncertainty = result.uncertainty / normalization
    return MasterFrame(
        data=normalized_data,
        uncertainty=normalized_uncertainty,
        n_combined=result.n_combined,
        kind="flat",
        filter_name=filter_name,
    )
