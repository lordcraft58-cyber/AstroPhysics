"""Corrección de iluminación -- equivalente propio de `mkillumflat`/
`mkillumcor` de IRAF: un flat de cúpula/dome corrige la respuesta píxel a
píxel del detector, pero no siempre reproduce el patrón de iluminación a
gran escala que ve el cielo real a través del sistema óptico completo (un
flat de cielo, tomado al atardecer/amanecer o combinando muchas LIGHTS
ditheradas, sí lo hace). Esta corrección aísla ese patrón de gran escala
-- suavizando fuertemente un flat ya normalizado para eliminar el ruido
píxel a píxel y cualquier resto de fuente puntual, dejando solo la
variación lenta -- y lo aplica como un segundo divisor, independiente del
flat de respuesta que ya aplica `calibration.calibrate_frame`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage


@dataclass(frozen=True)
class IlluminationMap:
    data: np.ndarray
    """Patrón de iluminación a gran escala, normalizado a mediana 1.0."""
    smoothing_sigma_px: float


def build_illumination_map(flat_data: np.ndarray, *, smoothing_sigma_px: float = 25.0) -> IlluminationMap:
    """Suaviza `flat_data` (normalmente un flat maestro ya normalizado a
    mediana 1.0, ver `master_frames.build_master_flat`) con un filtro
    gaussiano de sigma `smoothing_sigma_px` -- grande frente al tamaño de
    cualquier defecto de píxel o estrella residual, pero pequeño frente a
    las dimensiones de la imagen -- para aislar solo la variación de gran
    escala, y renormaliza el resultado a mediana 1.0.
    """
    if smoothing_sigma_px <= 0:
        raise ValueError("smoothing_sigma_px debe ser positivo")
    smoothed = ndimage.gaussian_filter(flat_data.astype(np.float64), sigma=smoothing_sigma_px)
    normalization = float(np.median(smoothed))
    if normalization <= 0:
        raise ValueError(f"la mediana del patrón de iluminación suavizado no es positiva ({normalization})")
    return IlluminationMap(data=smoothed / normalization, smoothing_sigma_px=smoothing_sigma_px)


def apply_illumination_correction(data: np.ndarray, illumination: IlluminationMap) -> np.ndarray:
    """Divide `data` (ya calibrada de bias/dark/flat) por el patrón de
    iluminación -- el mismo tipo de operación que un flat de respuesta,
    pero dirigida solo a la variación de gran escala."""
    if data.shape != illumination.data.shape:
        raise ValueError(f"data e illumination deben tener la misma forma; {data.shape} != {illumination.data.shape}")
    return data.astype(np.float64) / illumination.data
