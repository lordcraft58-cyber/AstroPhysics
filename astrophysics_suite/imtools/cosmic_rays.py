"""Detección y eliminación de rayos cósmicos -- equivalente propio de
`crmedian`/L.A.Cosmic de IRAF (van Dokkum 2001, PASP 113, 1420),
reimplementado desde la descripción del algoritmo con numpy/scipy
vectorizado, no envuelto desde ningún binario ni biblioteca de terceros.

Idea central del algoritmo: un rayo cósmico tiene un perfil espacial
mucho más puntiagudo que la peor PSF posible (ocupa literalmente un
píxel o una traza de pocos píxeles con bordes duros), así que su
Laplaciano espacial es desproporcionadamente grande comparado con el
ruido esperado en ese píxel -- a diferencia de una estrella real, cuyo
pico, por muy afilado que sea, siempre está suavizado por la PSF. El
truco de submuestrear x2 antes del Laplaciano (en vez de aplicarlo
directamente) evita que los propios píxeles individuales de una estrella
bien muestreada disparen falsos positivos en el borde de su perfil.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np
from scipy import ndimage

_LAPLACIAN_KERNEL = np.array([[0.0, -1.0, 0.0], [-1.0, 4.0, -1.0], [0.0, -1.0, 0.0]])


@dataclass(frozen=True)
class CosmicRayResult:
    cleaned_data: np.ndarray
    mask: np.ndarray
    """`True` donde se identificó (y limpió) un rayo cósmico."""
    n_pixels_flagged: int
    n_iterations_used: int

    @property
    def fraction_flagged(self) -> float:
        return self.n_pixels_flagged / self.mask.size if self.mask.size else 0.0


def _subsample_laplacian(data: np.ndarray) -> np.ndarray:
    """Submuestrea x2 (repetición de vecino más cercano), aplica el
    Laplaciano, recorta valores negativos (solo interesan los picos, no
    los valles) y vuelve a bajar de resolución promediando bloques 2x2 --
    la secuencia exacta del paso "Laplacian edge detection" del algoritmo
    original."""
    upsampled = np.repeat(np.repeat(data, 2, axis=0), 2, axis=1)
    laplacian = ndimage.convolve(upsampled, _LAPLACIAN_KERNEL, mode="mirror")
    laplacian = np.clip(laplacian, a_min=0.0, a_max=None)
    h, w = data.shape
    return laplacian.reshape(h, 2, w, 2).mean(axis=(1, 3))


def _noise_model(median5: np.ndarray, *, gain_e_per_adu: float, read_noise_e: float) -> np.ndarray:
    signal_e = np.clip(median5, a_min=0.0, a_max=None) * gain_e_per_adu
    noise_e = np.sqrt(signal_e + read_noise_e**2)
    return np.clip(noise_e / gain_e_per_adu, a_min=1e-6, a_max=None)


def _fine_structure_image(data: np.ndarray, *, floor: float) -> np.ndarray:
    """Imagen de "estructura fina": lo que sobrevive a restar dos
    medianas de distinta escala (3x3 y 7x7). Una estrella real conserva
    estructura fina suave en esta imagen; un rayo cósmico, al ser casi un
    delta, apenas deja huella -- de ahí que la razón L/F (`objlim`) sea el
    segundo criterio, independiente del de significancia estadística
    (`sigclip`), y el que de verdad distingue rayos cósmicos de núcleos
    estelares saturados de forma natural."""
    m3 = ndimage.median_filter(data, size=3, mode="mirror")
    m3_7 = ndimage.median_filter(m3, size=7, mode="mirror")
    return np.clip(m3 - m3_7, a_min=floor, a_max=None)


def detect_cosmic_rays(
    data: np.ndarray,
    *,
    gain_e_per_adu: float = 1.0,
    read_noise_e: float = 5.0,
    sigclip: float = 4.5,
    sigfrac: float = 0.3,
    objlim: float = 5.0,
    satlevel: float | None = None,
    niter: int = 4,
    fine_structure_floor: float = 0.01,
) -> CosmicRayResult:
    """Detecta y limpia rayos cósmicos en una imagen 2D en ADU (ya
    corregida de bias -- aplicar tras `reduction.calibration`, nunca
    antes, o el patrón de bias inflará falsos positivos).

    Parámetros con el mismo significado que en L.A.Cosmic/`crmedian`:
    `sigclip` es el umbral de significancia (en sigma de ruido) para que
    un píxel se considere candidato; `sigfrac` es la fracción de
    `sigclip` usada para hacer crecer la máscara hacia píxeles vecinos
    menos significativos pero probablemente parte del mismo rayo;
    `objlim` es el umbral mínimo de la razón Laplaciano/estructura-fina
    que separa un rayo cósmico de un núcleo estelar puntiagudo;
    `satlevel`, si se da, excluye píxeles saturados de la detección (la
    saturación es un defecto distinto, no un rayo cósmico). `niter`
    itera todo el proceso sobre una copia de trabajo ya limpiada, para
    que rayos cósmicos solapados o con núcleos brillantes se terminen de
    resolver -- se detiene antes si una iteración no añade píxeles
    nuevos.
    """
    if data.ndim != 2:
        raise ValueError(f"detect_cosmic_rays opera sobre imágenes 2D; recibido ndim={data.ndim}")
    if gain_e_per_adu <= 0:
        raise ValueError("gain_e_per_adu debe ser positivo")

    working = data.astype(np.float64).copy()
    mask = np.zeros(data.shape, dtype=bool)
    saturated = data >= satlevel if satlevel is not None else np.zeros(data.shape, dtype=bool)
    iterations_used = 0

    for iteration in range(max(1, niter)):
        iterations_used = iteration + 1
        laplacian = _subsample_laplacian(working)
        median5 = ndimage.median_filter(working, size=5, mode="mirror")
        noise = _noise_model(median5, gain_e_per_adu=gain_e_per_adu, read_noise_e=read_noise_e)

        significance = laplacian / (2.0 * noise)
        significance_smooth = significance - ndimage.median_filter(significance, size=5, mode="mirror")

        fine_structure = _fine_structure_image(working, floor=fine_structure_floor)
        contrast = laplacian / fine_structure

        strict_candidates = (significance_smooth > sigclip) & (contrast > objlim) & ~saturated
        if not np.any(strict_candidates):
            break

        grown = ndimage.binary_dilation(strict_candidates, structure=np.ones((3, 3), dtype=bool))
        loose_candidates = (significance_smooth > sigclip * sigfrac) & ~saturated
        new_mask = (strict_candidates | (grown & loose_candidates)) & ~mask

        if not np.any(new_mask):
            break

        mask |= new_mask
        # `median5` (mediana 5x5, ya calculada para el modelo de ruido de
        # esta iteración) es en sí misma una buena estimación robusta del
        # valor local "sin rayo cósmico": un solo píxel contaminado entre
        # 25 no puede desplazar la mediana de la ventana. Se evita así un
        # filtro de mediana consciente de máscara (scipy.ndimage no
        # soporta NaN de forma fiable en median_filter) sin sacrificar
        # robustez frente a rayos cósmicos aislados.
        working = np.where(mask, median5, working)

    return CosmicRayResult(
        cleaned_data=working,
        mask=mask,
        n_pixels_flagged=int(np.count_nonzero(mask)),
        n_iterations_used=iterations_used,
    )
