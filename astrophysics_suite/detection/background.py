"""Estimación de fondo de cielo en mosaico (tile) con su RMS local --
el mapa que necesita cualquier detector de fuentes puntuales para saber,
píxel a píxel, qué nivel es "cielo" y qué desviación por encima de ese
nivel es estadísticamente significativa.

No es el mismo problema que `reduction/sky.py::fit_sky_background`: ahí
se ajusta una única superficie polinómica suave (para RESTARLA de la
imagen calibrada). Aquí se necesita además el RMS LOCAL por mosaico
-- el ruido real de cada zona, no una superficie global -- porque de
ahí sale el umbral de detección (`threshold_sigma * rms`). Mezclar los
dos sería resolver un problema con la herramienta del otro.

Migrado de `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.estimate_background`
(docs/audit/54-CIERRE-DETECTION.md). Comportamiento observable
conservado: `tests/regression/test_detection_matches_legacy.py` compara
campo a campo contra la implementación original.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np
from photutils.background import Background2D, MedianBackground
from scipy import ndimage as ndi

try:
    # photutils >= 2.0 dejó de reexportar SigmaClip (ahora vive solo en
    # astropy.stats) -- sin este fallback, la importación de arriba no
    # falla (Background2D/MedianBackground siguen existiendo), pero
    # importar SigmaClip desde photutils.background sí revienta con
    # ImportError en cualquier instalación reciente (verificado con
    # photutils 3.0.0, la versión realmente instalada en este entorno).
    from photutils.background import SigmaClip
except ImportError:
    from astropy.stats import SigmaClip

_MAD_TO_SIGMA = 1.4826


@dataclass(frozen=True)
class Background:
    bkg: np.ndarray
    """Nivel de fondo estimado, misma forma que la imagen de entrada."""
    rms: np.ndarray
    """Ruido local estimado, misma forma -- nunca cero (suelo de 1e-12)."""
    box: int
    """Tamaño de mosaico (px) usado para la estimación."""

    def subtract(self, data: np.ndarray) -> np.ndarray:
        return data - self.bkg


def _robust_stats(x: np.ndarray, clip_sigma: float = 3.0, iters: int = 5) -> tuple[float, float]:
    """Mediana y MAD (escalada a sigma) con rechazo iterativo -- misma
    convención MAD*1.4826 que ya usa el resto del producto
    (`reduction/combine.py`, `imtools/statistics.py`)."""
    a = np.asarray(x, dtype=np.float64).ravel()
    a = a[np.isfinite(a)]
    if a.size == 0:
        return 0.0, 1.0
    for _ in range(iters):
        med = np.median(a)
        mad = _MAD_TO_SIGMA * np.median(np.abs(a - med))
        if mad <= 0:
            mad = np.std(a)
            break
        keep = np.abs(a - med) < clip_sigma * mad
        if keep.all():
            break
        a = a[keep]
    med = float(np.median(a))
    mad = float(_MAD_TO_SIGMA * np.median(np.abs(a - med)))
    return med, max(mad, 1e-12)


def _estimate_background_tiled(
    data: np.ndarray, box: int, filter_size: int, clip_sigma: float, mask: np.ndarray | None
) -> Background:
    """Reserva sin `photutils.Background2D`: mosaico manual con
    estadística robusta por tesela e interpolación de spline al tamaño
    completo de la imagen -- el mismo algoritmo que `Background2D`
    resuelve internamente, en Python puro. Se usa solo si
    `Background2D` no está disponible o falla en tiempo real (p. ej.
    una imagen degenerada); con `photutils` como dependencia dura del
    producto, esta rama rara vez se ejecuta -- pero cuando lo hace,
    debe seguir dando un fondo utilizable, no una excepción."""
    a = np.asarray(data, np.float32)
    ext_mask = ~np.isfinite(a)
    if mask is not None:
        ext_mask |= np.asarray(mask, bool)
    height, width = a.shape
    ny = max(1, math.ceil(height / box))
    nx = max(1, math.ceil(width / box))
    tile_bkg = np.zeros((ny, nx), dtype=float)
    tile_rms = np.zeros((ny, nx), dtype=float)
    for j in range(ny):
        for i in range(nx):
            tile = a[j * box : (j + 1) * box, i * box : (i + 1) * box]
            tile_mask = ext_mask[j * box : (j + 1) * box, i * box : (i + 1) * box]
            tile = np.where(tile_mask, np.nan, tile)
            tile_bkg[j, i], tile_rms[j, i] = _robust_stats(tile, clip_sigma)
    if filter_size > 1 and min(ny, nx) >= filter_size:
        tile_bkg = ndi.median_filter(tile_bkg, size=filter_size, mode="nearest")
        tile_rms = ndi.median_filter(tile_rms, size=filter_size, mode="nearest")
    yy = (np.arange(height) + 0.5) / box - 0.5
    xx = (np.arange(width) + 0.5) / box - 0.5
    grid_y, grid_x = np.meshgrid(np.clip(yy, 0, ny - 1), np.clip(xx, 0, nx - 1), indexing="ij")
    order_bkg = 3 if min(ny, nx) >= 4 else 1
    bkg = ndi.map_coordinates(tile_bkg, [grid_y, grid_x], order=order_bkg, mode="nearest").astype(np.float32)
    rms = ndi.map_coordinates(tile_rms, [grid_y, grid_x], order=1, mode="nearest").astype(np.float32)
    return Background(bkg=bkg, rms=np.maximum(rms, 1e-12), box=box)


def estimate_background(
    data: np.ndarray,
    box: int = 64,
    filter_size: int = 3,
    clip_sigma: float = 3.0,
    mask: np.ndarray | None = None,
    use_photutils: bool = True,
) -> Background:
    """Estima fondo y RMS local en mosaicos de `box` x `box` píxeles.

    `mask`, si se da, marca píxeles a excluir de la estadística además
    de los no finitos (p. ej. una máscara provisional de estrellas, para
    no dejar que su brillo sesgue el nivel de "cielo" estimado).

    `use_photutils=False` fuerza la reserva en Python puro incluso con
    `photutils` disponible -- pensado para poder probar esa rama de
    forma determinista, no para uso en producción.
    """
    array = np.asarray(data, np.float32)
    if array.ndim != 2:
        raise ValueError(f"estimate_background requiere 2D, recibido {array.shape}")
    ext_mask = ~np.isfinite(array)
    if mask is not None:
        ext_mask |= np.asarray(mask, bool)

    if use_photutils:
        try:
            box_size = (max(8, int(box)), max(8, int(box)))
            sigma_clip = SigmaClip(sigma=float(clip_sigma), maxiters=5)
            result = Background2D(
                array, box_size=box_size, filter_size=(3, 3),
                sigma_clip=sigma_clip, bkg_estimator=MedianBackground(), mask=ext_mask,
            )
            return Background(
                bkg=np.asarray(result.background, np.float32),
                rms=np.maximum(np.asarray(result.background_rms, np.float32), 1e-12),
                box=int(box),
            )
        except Exception:
            # Background2D puede fallar en datos degenerados (imagen
            # diminuta, completamente enmascarada); la reserva sigue
            # dando un fondo utilizable en vez de propagar la excepción.
            pass
    return _estimate_background_tiled(array, box, filter_size, clip_sigma, mask)
