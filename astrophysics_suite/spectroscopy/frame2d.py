"""Modelo de datos de una imagen espectroscópica 2D y de su máscara de
calidad por píxel -- la pieza que faltaba para que la extracción
(`trace.py`) pueda distinguir un 0 VÁLIDO (bias ya restado, cielo bajo)
de un píxel realmente inválido (NaN, Inf, saturado, muerto, marcado a
mano), en vez de tratar todo lo que no es NaN como flujo real.

Encontrado auditando el módulo con FITS reales del usuario (Vega,
T CrB): `trace_spectrum`/`extract_sum`/`extract_optimal` no tenían
ningún concepto de "píxel malo" -- sumaban directamente lo que hubiera
en el array, incluidos los píxeles muertos reales de la cámara (1397 en
un solo frame de Vega, 27 de ellos dentro de la propia banda de la
traza). Este módulo es la base de datos/contrato; `trace.py` lo consume.
"""
from __future__ import annotations

from enum import IntFlag
from typing import Any

import numpy as np


class PixelFlag(IntFlag):
    """Motivo por el que un píxel no debe tratarse como flujo real.
    Combinable a nivel de bits -- un píxel puede ser, por ejemplo,
    SATURATED y estar además en un COSMIC_RAY detectado en la misma
    pasada."""

    GOOD = 0
    NONFINITE = 1
    """NaN o Inf -- nunca puede ser un valor de flujo válido, con o sin
    máscara externa."""
    SATURATED = 2
    DEAD = 4
    """Píxel muerto/caliente conocido de la cámara -- requiere que el
    llamador aporte su propia máscara de píxeles defectuosos; nunca se
    infiere de que el valor sea 0 (un 0 puede ser perfectamente un
    flujo real bajo, ya con el bias restado)."""
    COSMIC_RAY = 8
    USER_MASKED = 16
    """Marcado a mano por el usuario en la GUI (región de traza
    truncada, artefacto conocido, etc.)."""


def build_pixel_mask(
    data: np.ndarray,
    *,
    saturate_adu: float | None = None,
    dead_pixel_mask: np.ndarray | None = None,
    cosmic_ray_mask: np.ndarray | None = None,
    user_mask: np.ndarray | None = None,
) -> np.ndarray:
    """Construye la máscara de calidad de `data`, combinando bit a bit
    (`PixelFlag`) solo lo que se puede justificar con evidencia real:

    - `NONFINITE` siempre, de los propios datos -- no es una opción.
    - `SATURATED` solo si se da `saturate_adu` (típicamente
      `header['SATURATE']`); sin él, la detección de saturación queda
      inactiva, igual que ya hace `detection.finder.enrich_detections`
      (no se inventa un umbral).
    - `DEAD`/`COSMIC_RAY`/`USER_MASKED` solo si el llamador aporta su
      propia máscara booleana (misma forma que `data`, `True` = píxel
      afectado) -- nunca se infieren de los valores de `data` por sí
      solos, porque un 0 o un valor bajo pueden ser perfectamente
      reales.

    Devuelve un array `uint16` de la misma forma que `data`, con los
    bits de `PixelFlag` combinados (0 = GOOD).
    """
    array = np.asarray(data)
    mask = np.zeros(array.shape, dtype=np.uint16)
    mask[~np.isfinite(array)] |= np.uint16(PixelFlag.NONFINITE)
    if saturate_adu is not None and np.isfinite(saturate_adu) and saturate_adu > 0:
        mask[np.isfinite(array) & (array >= 0.999 * saturate_adu)] |= np.uint16(PixelFlag.SATURATED)
    for flag, external in (
        (PixelFlag.DEAD, dead_pixel_mask),
        (PixelFlag.COSMIC_RAY, cosmic_ray_mask),
        (PixelFlag.USER_MASKED, user_mask),
    ):
        if external is not None:
            external_bool = np.asarray(external, dtype=bool)
            if external_bool.shape != array.shape:
                raise ValueError(f"la máscara para {flag.name} debe tener la misma forma que data")
            mask[external_bool] |= np.uint16(flag)
    return mask


def is_bad(mask: np.ndarray | None, shape: tuple[int, ...]) -> np.ndarray:
    """`True` donde el píxel está marcado por cualquier motivo. Sin
    máscara (`mask is None`), todo se considera bueno -- una imagen sin
    máscara nunca se rechaza en silencio, se trata tal cual llegó."""
    if mask is None:
        return np.zeros(shape, dtype=bool)
    return np.asarray(mask, dtype=np.uint16) != PixelFlag.GOOD


class SpectralFrame2D:
    """Imagen espectroscópica 2D cruda o calibrada, con sus extensiones
    opcionales -- entidad (A)/(B) del modelo de datos espectroscópico.
    No asume que toda imagen trae varianza o máscara: ambas son
    opcionales y su ausencia se declara, nunca se rellena con un valor
    inventado.

    Convención de ejes, igual que `trace.py`: eje 0 = espacial, eje 1 =
    dispersión.
    """

    __slots__ = ("data", "variance", "mask", "header")

    def __init__(
        self,
        data: np.ndarray,
        *,
        variance: np.ndarray | None = None,
        mask: np.ndarray | None = None,
        header: dict[str, Any] | None = None,
    ) -> None:
        data = np.asarray(data, dtype=np.float64)
        if data.ndim != 2:
            raise ValueError("SpectralFrame2D requiere una imagen 2D (espacial x dispersión)")
        if variance is not None and np.asarray(variance).shape != data.shape:
            raise ValueError("variance debe tener la misma forma que data")
        if mask is not None and np.asarray(mask).shape != data.shape:
            raise ValueError("mask debe tener la misma forma que data")
        self.data = data
        self.variance = None if variance is None else np.asarray(variance, dtype=np.float64)
        self.mask = None if mask is None else np.asarray(mask, dtype=np.uint16)
        self.header = dict(header) if header else {}

    @property
    def uncertainty(self) -> np.ndarray | None:
        """`sqrt(variance)` si hay varianza real disponible -- `None`,
        nunca un valor inventado, si no la hay."""
        if self.variance is None:
            return None
        return np.sqrt(np.clip(self.variance, a_min=0.0, a_max=None))

    @property
    def is_bad(self) -> np.ndarray:
        return is_bad(self.mask, self.data.shape)

    @property
    def shape(self) -> tuple[int, int]:
        return self.data.shape  # type: ignore[return-value]
