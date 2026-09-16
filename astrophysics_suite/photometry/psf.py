"""Fotometría de PSF -- equivalente propio de `noao.digiphot.daophot` de
IRAF: modelos de PSF analíticos (Gaussiana, Moffat) y empíricos
(apilado de estrellas de referencia sobre una rejilla sobremuestreada),
más el ajuste simultáneo de amplitudes de flujo para varias fuentes que
comparten una misma región de imagen -- el mecanismo que permite
desmezclar (deblend) fuentes superpuestas, equivalente a `nstar`/
`allstar` de IRAF.

Todos los modelos de PSF están normalizados a **flujo total unitario**
(la integral 2D vale 1): así, el coeficiente que se ajusta en el paso de
mínimos cuadrados es directamente el flujo neto de la fuente en ADU, sin
ningún factor de conversión adicional.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol

import numpy as np
from scipy import ndimage


class PSFModel(Protocol):
    def evaluate(self, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        """Densidad de flujo (integral total = 1) en los desplazamientos
        `(dx, dy)` respecto al centro de la fuente, en píxeles."""
        ...


@dataclass(frozen=True)
class GaussianPSF:
    sigma_x: float
    sigma_y: float | None = None
    theta_rad: float = 0.0
    """Ángulo de rotación de los ejes cuando `sigma_x != sigma_y` (PSF
    elíptica -- p. ej. por *tracking* imperfecto o viento)."""

    def __post_init__(self) -> None:
        if self.sigma_x <= 0 or (self.sigma_y is not None and self.sigma_y <= 0):
            raise ValueError("sigma_x/sigma_y deben ser positivos")

    def evaluate(self, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        sigma_y = self.sigma_y if self.sigma_y is not None else self.sigma_x
        cos_t, sin_t = math.cos(self.theta_rad), math.sin(self.theta_rad)
        rx = dx * cos_t + dy * sin_t
        ry = -dx * sin_t + dy * cos_t
        normalization = 1.0 / (2.0 * math.pi * self.sigma_x * sigma_y)
        return normalization * np.exp(-0.5 * ((rx / self.sigma_x) ** 2 + (ry / sigma_y) ** 2))

    @property
    def fwhm_px(self) -> float:
        return 2.0 * math.sqrt(2.0 * math.log(2.0)) * self.sigma_x


@dataclass(frozen=True)
class MoffatPSF:
    """Perfil de Moffat -- colas más pesadas que una Gaussiana, el
    modelo analítico preferido de `daophot` para *seeing* atmosférico
    real (Moffat 1969, A&A 3, 455)."""

    alpha: float
    """Escala radial (px)."""
    beta: float
    """Índice de las colas -- beta grande se aproxima a una Gaussiana;
    beta pequeño (~2-3) da colas mucho más extendidas, típico del seeing
    real."""

    def __post_init__(self) -> None:
        if self.alpha <= 0 or self.beta <= 1:
            raise ValueError("alpha debe ser positivo y beta > 1 (para que la integral 2D converja)")

    def evaluate(self, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        r2 = dx**2 + dy**2
        normalization = (self.beta - 1.0) / (math.pi * self.alpha**2)
        return normalization * (1.0 + r2 / self.alpha**2) ** (-self.beta)

    @property
    def fwhm_px(self) -> float:
        return 2.0 * self.alpha * math.sqrt(2.0 ** (1.0 / self.beta) - 1.0)


@dataclass(frozen=True)
class EmpiricalPSF:
    """PSF construida promediando estrellas de referencia reales sobre
    una rejilla sobremuestreada -- captura aberraciones ópticas y
    asimetrías que ningún modelo analítico describe (la razón de ser de
    la PSF empírica en `daophot`, más allá de la Gaussiana/Moffat)."""

    template: np.ndarray
    """Rejilla cuadrada sobremuestreada, ya normalizada a suma 1."""
    oversample: int

    def evaluate(self, dx: np.ndarray, dy: np.ndarray) -> np.ndarray:
        half = self.template.shape[0] // 2
        grid_x = dx * self.oversample + half
        grid_y = dy * self.oversample + half
        values = ndimage.map_coordinates(self.template, [grid_y.ravel(), grid_x.ravel()], order=1, mode="constant", cval=0.0)
        return (values.reshape(dx.shape) * self.oversample**2)


def build_empirical_psf(
    data: np.ndarray,
    star_positions: list[tuple[float, float]],
    *,
    half_size: int = 9,
    oversample: int = 4,
    background: float = 0.0,
) -> EmpiricalPSF:
    """Extrae un recorte centrado subpíxel alrededor de cada estrella de
    referencia (desplazamiento fraccional vía interpolación bilineal,
    `scipy.ndimage.shift`), lo normaliza a flujo unitario y combina todas
    las estrellas por mediana -- robusto frente a una estrella de
    referencia contaminada por un vecino débil o un rayo cósmico."""
    if not star_positions:
        raise ValueError("build_empirical_psf necesita al menos una posición de referencia")
    if half_size < 2:
        raise ValueError("half_size debe ser >= 2")

    size = 2 * half_size + 1
    oversampled_size = size * oversample
    stamps: list[np.ndarray] = []

    for x0, y0 in star_positions:
        ix0, iy0 = int(round(x0)), int(round(y0))
        y_slice = slice(iy0 - half_size - 1, iy0 + half_size + 2)
        x_slice = slice(ix0 - half_size - 1, ix0 + half_size + 2)
        if y_slice.start < 0 or x_slice.start < 0 or y_slice.stop > data.shape[0] or x_slice.stop > data.shape[1]:
            continue
        cutout = data[y_slice, x_slice].astype(np.float64) - background
        frac_y, frac_x = y0 - iy0, x0 - ix0
        # `ndimage.shift(arr, s)` define output[c] = arr[c - s]; para que
        # el contenido que estaba en la posición fraccional de la
        # estrella (desplazada `frac` respecto al centro entero) termine
        # exactamente en el centro del recorte, el desplazamiento a
        # aplicar es `-frac` (no su opuesto).
        centered = ndimage.shift(cutout, shift=(-frac_y, -frac_x), order=3, mode="nearest")
        centered = centered[1 : 1 + size, 1 : 1 + size]
        oversampled = ndimage.zoom(centered, oversample, order=1)[:oversampled_size, :oversampled_size]
        total = np.sum(oversampled)
        if total <= 0:
            continue
        stamps.append(oversampled / total)

    if not stamps:
        raise ValueError("ninguna posición de referencia cabía completa dentro de la imagen")

    template = np.median(np.stack(stamps, axis=0), axis=0)
    template = np.clip(template, a_min=0.0, a_max=None)
    template_total = np.sum(template)
    if template_total <= 0:
        raise ValueError("la PSF empírica combinada no tiene flujo positivo")
    return EmpiricalPSF(template=template / template_total, oversample=oversample)


@dataclass(frozen=True)
class PSFFitResult:
    x: float
    y: float
    flux: float
    flux_uncertainty: float


def fit_group_psf_photometry(
    data: np.ndarray,
    uncertainty: np.ndarray,
    psf_model: PSFModel,
    positions: list[tuple[float, float]],
    *,
    fit_half_size: int = 7,
    fit_sky: bool = True,
) -> list[PSFFitResult]:
    """Ajuste simultáneo de flujo para un grupo de fuentes con posiciones
    fijas y forma de PSF compartida conocida -- el mecanismo real de
    desmezclado: cada fuente aporta una columna del sistema lineal
    (`amplitud_j * PSF(pixel_i - posicion_j)`), y resolver el sistema por
    mínimos cuadrados ponderados separa correctamente el flujo de cada
    una incluso cuando sus perfiles se solapan sustancialmente -- algo
    que ninguna apertura, por pequeña que sea, puede hacer sin sesgo.

    `fit_sky=True` (por defecto, igual que `nstar`/`allstar`) añade una
    columna constante al sistema para absorber el nivel de cielo local
    dentro del mismo ajuste: sin ella, cualquier fondo no nulo se
    reparte incorrectamente entre las colas de los perfiles de PSF y
    sesga sistemáticamente el flujo estimado hacia arriba. Se pone a
    `False` solo si `data` ya llega con el cielo restado (p. ej. la
    salida de `reduction.calibration`).

    Las posiciones se asumen fijas (ya centroided) -- ajustar también la
    posición (como hace `allstar` con actualizaciones no lineales) queda
    fuera de esta primera versión; ver docs/audit/11-FASE9-...
    """
    if not positions:
        raise ValueError("positions no puede estar vacío")
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")

    height, width = data.shape
    xs = np.array([p[0] for p in positions])
    ys = np.array([p[1] for p in positions])
    y_min = max(0, int(math.floor(ys.min())) - fit_half_size)
    y_max = min(height, int(math.ceil(ys.max())) + fit_half_size + 1)
    x_min = max(0, int(math.floor(xs.min())) - fit_half_size)
    x_max = min(width, int(math.ceil(xs.max())) + fit_half_size + 1)
    if y_min >= y_max or x_min >= x_max:
        raise ValueError("la caja de ajuste no cae dentro de la imagen")

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    pixel_values = data[y_min:y_max, x_min:x_max].ravel()
    pixel_sigma = uncertainty[y_min:y_max, x_min:x_max].ravel()
    weights = np.where(pixel_sigma > 0, 1.0 / pixel_sigma, 0.0)

    n_sources = len(positions)
    n_columns = n_sources + 1 if fit_sky else n_sources
    design_matrix = np.empty((pixel_values.size, n_columns))
    for j, (x0, y0) in enumerate(positions):
        design_matrix[:, j] = psf_model.evaluate((xx - x0).ravel(), (yy - y0).ravel())
    if fit_sky:
        design_matrix[:, n_sources] = 1.0

    weighted_design = design_matrix * weights[:, np.newaxis]
    weighted_values = pixel_values * weights

    solution, _residuals, rank, _sv = np.linalg.lstsq(weighted_design, weighted_values, rcond=None)

    fluxes_uncertainty = np.full(n_sources, float("nan"))
    if rank == n_columns:
        try:
            covariance = np.linalg.inv(weighted_design.T @ weighted_design)
            fluxes_uncertainty = np.sqrt(np.clip(np.diag(covariance)[:n_sources], a_min=0.0, a_max=None))
        except np.linalg.LinAlgError:
            pass

    return [
        PSFFitResult(x=x0, y=y0, flux=float(solution[j]), flux_uncertainty=float(fluxes_uncertainty[j]))
        for j, (x0, y0) in enumerate(positions)
    ]
