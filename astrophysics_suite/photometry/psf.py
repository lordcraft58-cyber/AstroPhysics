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

from astrophysics_suite.detection.point_sources import PSFCandidate


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


def select_psf_reference_stars(
    candidates: list[PSFCandidate],
    *,
    min_separation_px: float = 15.0,
    max_ellipticity: float = 0.3,
    min_snr: float = 15.0,
    max_stars: int = 12,
) -> list[PSFCandidate]:
    """Selección automática de estrellas de referencia para construir una
    PSF -- equivalente a `pstselect`: **aislamiento** (ningún otro
    candidato detectado, pase o no el resto de criterios, a menos de
    `min_separation_px`; un vecino aunque sea débil contamina la PSF
    apilada/el ajuste simultáneo), **redondez** (elipticidad baja -- una
    fuente alargada es más probable que sea un blend o un objeto
    extendido que una estrella real), y **señal/ruido** suficiente para
    que el centroide/perfil no esté dominado por ruido. Devuelve como
    máximo `max_stars`, de más a menos brillante entre las que cumplen
    todos los criterios -- nunca inventa una selección cuando ninguna
    cumple (lista vacía)."""
    isolated: list[PSFCandidate] = []
    for candidate in candidates:
        has_close_neighbor = any(
            other is not candidate and math.hypot(other.x - candidate.x, other.y - candidate.y) < min_separation_px
            for other in candidates
        )
        if not has_close_neighbor:
            isolated.append(candidate)

    selected = [c for c in isolated if c.ellipticity <= max_ellipticity and c.snr >= min_snr]
    selected.sort(key=lambda c: c.flux, reverse=True)
    return selected[:max_stars]


def fit_group_psf_photometry_with_position_refinement(
    data: np.ndarray,
    uncertainty: np.ndarray,
    psf_model: PSFModel,
    positions: list[tuple[float, float]],
    *,
    fit_half_size: int = 7,
    fit_sky: bool = True,
    max_position_shift_px: float = 3.0,
) -> list[PSFFitResult]:
    """Refinamiento no lineal iterativo de posición -- equivalente a
    `allstar`, a diferencia de `fit_group_psf_photometry` (posiciones
    fijas, solo el flujo se ajusta). Se resuelve por proyección variable
    (Golub-Pereyra): `scipy.optimize.least_squares` optimiza únicamente
    los 2 desplazamientos `(dx, dy)` de cada fuente respecto a su
    posición inicial; en cada evaluación, el flujo (y el cielo local) de
    todas las fuentes se resuelve como el mismo subproblema lineal exacto
    que usa `fit_group_psf_photometry` -- así el optimizador no lineal
    nunca necesita más de 2 parámetros por fuente, y el ajuste lineal
    interno sigue siendo el óptimo global para esa posición.

    La caja de píxeles usada en el ajuste se fija una sola vez a partir de
    las posiciones iniciales (más el margen de `max_position_shift_px`),
    no en cada iteración -- de lo contrario el vector de residuos
    cambiaría de tamaño con cada desplazamiento probado, lo que no encaja
    en `least_squares`."""
    from scipy.optimize import least_squares

    if not positions:
        raise ValueError("positions no puede estar vacío")
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")

    height, width = data.shape
    xs = np.array([p[0] for p in positions])
    ys = np.array([p[1] for p in positions])
    margin = fit_half_size + max_position_shift_px
    y_min = max(0, int(math.floor(ys.min() - margin)))
    y_max = min(height, int(math.ceil(ys.max() + margin)) + 1)
    x_min = max(0, int(math.floor(xs.min() - margin)))
    x_max = min(width, int(math.ceil(xs.max() + margin)) + 1)
    if y_min >= y_max or x_min >= x_max:
        raise ValueError("la caja de ajuste no cae dentro de la imagen")

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    pixel_values = data[y_min:y_max, x_min:x_max].ravel()
    pixel_sigma = uncertainty[y_min:y_max, x_min:x_max].ravel()
    weights = np.where(pixel_sigma > 0, 1.0 / pixel_sigma, 0.0)
    weighted_values = pixel_values * weights

    n_sources = len(positions)
    n_columns = n_sources + 1 if fit_sky else n_sources

    def solve_linear(current_positions: list[tuple[float, float]]):
        design_matrix = np.empty((pixel_values.size, n_columns))
        for j, (x0, y0) in enumerate(current_positions):
            design_matrix[:, j] = psf_model.evaluate((xx - x0).ravel(), (yy - y0).ravel())
        if fit_sky:
            design_matrix[:, n_sources] = 1.0
        weighted_design = design_matrix * weights[:, np.newaxis]
        solution, _residuals, rank, _sv = np.linalg.lstsq(weighted_design, weighted_values, rcond=None)
        return solution, weighted_design, rank

    def residuals_for_offsets(offsets_flat: np.ndarray) -> np.ndarray:
        offsets = offsets_flat.reshape(n_sources, 2)
        current_positions = [(x0 + dx, y0 + dy) for (x0, y0), (dx, dy) in zip(positions, offsets)]
        solution, weighted_design, _rank = solve_linear(current_positions)
        return weighted_design @ solution - weighted_values

    initial_offsets = np.zeros(2 * n_sources)
    bounds = (np.full(2 * n_sources, -max_position_shift_px), np.full(2 * n_sources, max_position_shift_px))
    result = least_squares(residuals_for_offsets, initial_offsets, bounds=bounds)

    final_offsets = result.x.reshape(n_sources, 2)
    refined_positions = [(x0 + dx, y0 + dy) for (x0, y0), (dx, dy) in zip(positions, final_offsets)]
    solution, weighted_design, rank = solve_linear(refined_positions)

    fluxes_uncertainty = np.full(n_sources, float("nan"))
    if rank == n_columns:
        try:
            covariance = np.linalg.inv(weighted_design.T @ weighted_design)
            fluxes_uncertainty = np.sqrt(np.clip(np.diag(covariance)[:n_sources], a_min=0.0, a_max=None))
        except np.linalg.LinAlgError:
            pass

    return [
        PSFFitResult(x=float(x), y=float(y), flux=float(solution[j]), flux_uncertainty=float(fluxes_uncertainty[j]))
        for j, (x, y) in enumerate(refined_positions)
    ]


@dataclass(frozen=True)
class PSFFitDiagnostics:
    chi2: float
    reduced_chi2: float
    """Estadístico chi-cuadrado reducido -- equivalente al `CHI` que
    reporta `nstar`/`allstar`: ~1 indica que el modelo de PSF explica los
    residuos dentro del ruido esperado; sistemáticamente > 1 sugiere un
    modelo de PSF insuficiente (p. ej. Gaussiana para un perfil con colas
    más pesadas) o una incertidumbre subestimada."""
    n_pixels_used: int
    n_free_parameters: int
    sky_level: float
    residual_image: np.ndarray
    """Imagen (datos - modelo) recortada a la caja de ajuste -- estructura
    sistemática visible aquí (anillos, un pico residual) es la señal
    clásica de un modelo de PSF que no describe bien la fuente real."""
    bbox: tuple[int, int, int, int]
    """(y_min, y_max, x_min, x_max) -- posición de `residual_image` dentro
    de la imagen original."""


def compute_psf_fit_diagnostics(
    data: np.ndarray,
    uncertainty: np.ndarray,
    psf_model: PSFModel,
    fit_results: list[PSFFitResult],
    *,
    fit_half_size: int = 7,
    fit_sky: bool = True,
) -> PSFFitDiagnostics:
    """Diagnóstico de calidad para un ajuste PSF ya resuelto (posiciones y
    flujos de `fit_group_psf_photometry` o su variante con refinamiento de
    posición) -- equivalente al diagnóstico que reporta `nstar`/`allstar`
    tras el ajuste, no durante él: no vuelve a resolver flujos ni
    posiciones, solo reconstruye el modelo con los resultados dados y lo
    compara con los datos reales.

    El nivel de cielo no viaja en `PSFFitResult` (por diseño: mantiene ese
    contrato estable) -- si `fit_sky=True`, se recupera aquí con un ajuste
    lineal de 1 parámetro (media ponderada por varianza inversa del
    residuo tras restar solo el modelo de fuentes), la misma cantidad que
    ya resolvió el ajuste original como parte del mismo sistema lineal."""
    if not fit_results:
        raise ValueError("fit_results no puede estar vacío")
    height, width = data.shape
    xs = np.array([r.x for r in fit_results])
    ys = np.array([r.y for r in fit_results])
    y_min = max(0, int(math.floor(ys.min())) - fit_half_size)
    y_max = min(height, int(math.ceil(ys.max())) + fit_half_size + 1)
    x_min = max(0, int(math.floor(xs.min())) - fit_half_size)
    x_max = min(width, int(math.ceil(xs.max())) + fit_half_size + 1)
    if y_min >= y_max or x_min >= x_max:
        raise ValueError("la caja de ajuste no cae dentro de la imagen")

    yy, xx = np.mgrid[y_min:y_max, x_min:x_max]
    source_model = np.zeros(xx.shape, dtype=np.float64)
    for r in fit_results:
        source_model += r.flux * psf_model.evaluate(xx - r.x, yy - r.y)

    observed = data[y_min:y_max, x_min:x_max]
    sigma = uncertainty[y_min:y_max, x_min:x_max]
    valid = sigma > 0
    residual_before_sky = observed - source_model

    sky_level = 0.0
    if fit_sky and np.any(valid):
        inverse_variance = np.where(valid, 1.0 / np.clip(sigma, 1e-12, None) ** 2, 0.0)
        sky_level = float(np.sum(residual_before_sky * inverse_variance) / np.sum(inverse_variance))

    residual = residual_before_sky - sky_level
    chi2 = float(np.sum((residual[valid] / sigma[valid]) ** 2))
    n_pixels_used = int(np.sum(valid))
    n_free_parameters = len(fit_results) + (1 if fit_sky else 0)
    reduced_chi2 = chi2 / max(n_pixels_used - n_free_parameters, 1)

    return PSFFitDiagnostics(
        chi2=chi2,
        reduced_chi2=reduced_chi2,
        n_pixels_used=n_pixels_used,
        n_free_parameters=n_free_parameters,
        sky_level=sky_level,
        residual_image=residual,
        bbox=(y_min, y_max, x_min, x_max),
    )
