"""Combinación de N imágenes en una sola -- el núcleo de `imcombine` de
IRAF, reimplementado con numpy vectorizado (sin bucles por píxel).

Soporta mediana o media, con rechazo iterativo por sigma-clipping robusto
(MAD, no desviación estándar clásica -- más resistente a que un solo
rayo cósmico infle la varianza estimada y esconda al resto) antes de la
combinación final. Es el bloque compartido que usan tanto
`master_frames.py` (bias/dark/flat maestros) como cualquier apilado
genérico de exposiciones científicas alineadas.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826
"""Factor que convierte la desviación absoluta mediana (MAD) en un
estimador consistente de sigma para una distribución gaussiana."""


@dataclass(frozen=True)
class CombineResult:
    data: np.ndarray
    uncertainty: np.ndarray
    """Error estándar de la media/mediana combinada por píxel --
    `sigma_robusta / sqrt(n_usados)`, nunca `sigma_robusta` sola (eso
    sería la dispersión de la pila, no la incertidumbre del resultado)."""
    n_combined: np.ndarray
    """Cuántas imágenes de entrada sobrevivieron el rechazo en cada
    píxel (mismo ancho/alto que `data`; puede variar píxel a píxel)."""
    n_input: int
    method: str


def combine_images(
    images: list[np.ndarray],
    *,
    method: str = "median",
    sigma_clip: float | None = 3.0,
    max_iters: int = 5,
) -> CombineResult:
    """Combina una pila de imágenes ya alineadas (misma forma). Si
    `sigma_clip` no es `None`, rechaza iterativamente -- por píxel -- los
    valores que se desvían más de `sigma_clip` sigmas robustas de la
    mediana de la pila en esa iteración, hasta `max_iters` veces o hasta
    que no se rechace nada nuevo.
    """
    if not images:
        raise ValueError("combine_images requiere al menos una imagen")
    if method not in ("median", "mean"):
        raise ValueError(f"method debe ser 'median' o 'mean'; recibido {method!r}")
    shape = images[0].shape
    for image in images[1:]:
        if image.shape != shape:
            raise ValueError(f"todas las imágenes deben tener la misma forma; {image.shape} != {shape}")

    stack = np.stack([image.astype(np.float64) for image in images], axis=0)
    n_input = stack.shape[0]
    rejected = np.zeros(stack.shape, dtype=bool)

    if sigma_clip is not None and n_input >= 3:
        for _ in range(max_iters):
            working = np.where(rejected, np.nan, stack)
            center = np.nanmedian(working, axis=0)
            abs_dev = np.abs(working - center)
            mad = np.nanmedian(abs_dev, axis=0)
            robust_sigma = np.clip(mad * _MAD_TO_SIGMA, a_min=1e-9, a_max=None)
            new_rejected = (abs_dev > sigma_clip * robust_sigma) & ~np.isnan(working)
            # nunca rechazar el último superviviente de un píxel: sin eso, un
            # píxel con solo 1-2 entradas válidas podría quedarse sin ninguna.
            survivors_after = np.count_nonzero(~(rejected | new_rejected), axis=0)
            new_rejected &= survivors_after[np.newaxis, ...] > 0
            if not np.any(new_rejected & ~rejected):
                break
            rejected |= new_rejected

    masked_stack = np.where(rejected, np.nan, stack)
    n_combined = np.count_nonzero(~rejected, axis=0)

    if method == "median":
        combined = np.nanmedian(masked_stack, axis=0)
    else:
        combined = np.nanmean(masked_stack, axis=0)

    abs_dev_final = np.abs(masked_stack - combined[np.newaxis, ...])
    mad_final = np.nanmedian(abs_dev_final, axis=0)
    robust_sigma_final = mad_final * _MAD_TO_SIGMA
    safe_n = np.clip(n_combined, a_min=1, a_max=None)
    uncertainty = robust_sigma_final / np.sqrt(safe_n)
    # con una sola imagen combinada por píxel no hay forma de estimar
    # dispersión de la pila -- se deja en 0.0 en vez de un NaN/inf
    # engañoso; el llamador conoce `n_combined` y puede decidir si eso es
    # aceptable para su caso de uso.
    uncertainty = np.where(n_combined <= 1, 0.0, uncertainty)

    return CombineResult(data=combined, uncertainty=uncertainty, n_combined=n_combined, n_input=n_input, method=method)
