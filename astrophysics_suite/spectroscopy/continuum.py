"""Ajuste de continuo -- equivalente propio de `continuum` de IRAF:
ajuste polinómico iterativo con sigma-clipping que rechaza asimétricamente
las líneas (de emisión o de absorción, según se indique) para converger
a una estimación suave del continuo subyacente, y normalización del
espectro dividiendo por ese ajuste.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

_MAD_TO_SIGMA = 1.4826


_CONTINUUM_METHODS = ("polynomial", "spline")


def _robust_noise_variance(y: np.ndarray) -> float:
    """Estima la varianza real del ruido punto a punto vía la MAD de las
    diferencias consecutivas -- robusta frente a un puñado de líneas
    aisladas (una línea de pocos píxeles solo contamina un par de
    diferencias, una fracción pequeña del total). Sirve para fijar un
    factor de suavizado spline por defecto que no persiga el ruido (ni,
    peor, una línea que todavía no se ha rechazado)."""
    if y.size < 3:
        return 0.0
    diffs = np.diff(y)
    mad = float(np.median(np.abs(diffs - np.median(diffs))))
    sigma = _MAD_TO_SIGMA * mad / math.sqrt(2.0)
    return sigma**2


def _fit_continuum_curve(x: np.ndarray, y: np.ndarray, *, method: str, degree: int, spline_smoothing: float | None):
    """Mismo patrón que `trace._fit_curve` (§2/§19: "spline como
    alternativa al polinomio"), reimplementado aquí en vez de importado
    para no crear una dependencia cruzada entre `trace.py` y
    `continuum.py` por una función de 10 líneas."""
    if method == "polynomial":
        coefficients = np.polyfit(x, y, deg=degree)
        return coefficients, (lambda values: np.polyval(coefficients, values))
    if method == "spline":
        from scipy.interpolate import UnivariateSpline

        k = min(degree, 5, x.size - 1)
        if k < 1:
            raise ValueError(f"se necesitan al menos 2 puntos para un ajuste spline (hay {x.size})")
        # `s=None` dejaría que scipy use `s=len(w)` con peso unitario, que
        # infraestima la suavidad necesaria frente a una línea todavía sin
        # rechazar -- se estima la varianza real del ruido en su lugar
        # (documentación de scipy: `s` recomendado ~ `len(w) * varianza`).
        s = float(x.size) * _robust_noise_variance(y) if spline_smoothing is None else spline_smoothing
        spline = UnivariateSpline(x, y, k=k, s=s)
        return np.array([]), spline
    raise ValueError(f"method debe ser uno de {_CONTINUUM_METHODS}, recibido {method!r}")


def _region_mask(wavelength: np.ndarray, regions: tuple[tuple[float, float], ...]) -> np.ndarray:
    """`True` en los puntos que caen dentro de alguna región real de
    continuo indicada a mano (§19) -- unión de todos los intervalos
    `[lo, hi]` dados, ambos límites inclusive."""
    mask = np.zeros(wavelength.size, dtype=bool)
    for lo, hi in regions:
        if hi < lo:
            lo, hi = hi, lo
        mask |= (wavelength >= lo) & (wavelength <= hi)
    return mask


@dataclass(frozen=True)
class ContinuumFit:
    coefficients: np.ndarray
    """Coeficientes reales del polinomio (`method="polynomial"`), o un
    array vacío si `method="spline"` (un spline no tiene coeficientes
    polinómicos únicos que reportar -- la curva ajustada real sigue
    disponible en `continuum`)."""
    continuum: np.ndarray
    """Continuo evaluado en cada píxel de entrada."""
    rms_residual: float
    n_rejected: int
    used_mask: np.ndarray
    """`True` en los píxeles que sí participaron en el ajuste final --
    `False` en los rechazados por línea (según `reject`) o fuera de
    `regions` si se dieron regiones manuales (§19)."""
    method: str = "polynomial"
    """§19: "polynomial" (por defecto) o "spline"."""


def fit_continuum(
    wavelength: np.ndarray,
    flux: np.ndarray,
    *,
    degree: int = 3,
    method: str = "polynomial",
    spline_smoothing: float | None = None,
    sigma_clip: float = 2.5,
    max_iters: int = 10,
    reject: str = "both",
    regions: tuple[tuple[float, float], ...] | None = None,
) -> ContinuumFit:
    """Ajusta una curva de continuo a `flux(wavelength)`, rechazando
    iterativamente los puntos que se desvían más de `sigma_clip` sigmas
    robustas (MAD) del ajuste actual.

    `method` (§19): `"polynomial"` (por defecto, `np.polyfit(deg=
    degree)`) o `"spline"` (`scipy.interpolate.UnivariateSpline`, grado
    `min(degree, 5)`, factor de suavizado `spline_smoothing` -- `None`
    deja que scipy lo estime).

    `regions` (§19): si se da, una tupla de pares reales `(lo, hi)` en
    las mismas unidades que `wavelength` -- SOLO los puntos dentro de
    alguna de esas regiones entran en el ajuste inicial (selección
    manual de continuo, en vez de dejar que el sigma-clip automático
    decida qué es línea y qué es continuo). El rechazo iterativo sigue
    aplicándose DENTRO de esas regiones, nunca las amplía por su cuenta.
    Lanza `ValueError` honesto si ningún punto real cae dentro de
    `regions`.

    `reject`:
      - "both": rechaza por encima Y por debajo (uso general).
      - "emission": rechaza solo por encima (líneas de emisión que no
        deben tirar el continuo hacia arriba; absorciones se dejan
        influir el ajuste, apropiado para continuo estelar con líneas de
        absorción que SÍ se quiere seguir de cerca).
      - "absorption": rechaza solo por debajo (simétrico al anterior,
        para espectros dominados por líneas de emisión sobre un continuo
        débil).
    """
    if wavelength.shape != flux.shape:
        raise ValueError("wavelength y flux deben tener la misma forma")
    if method not in _CONTINUUM_METHODS:
        raise ValueError(f"method debe ser uno de {_CONTINUUM_METHODS}, recibido {method!r}")
    if reject not in ("both", "emission", "absorption"):
        raise ValueError(f"reject debe ser 'both', 'emission' o 'absorption'; recibido {reject!r}")
    if wavelength.size < degree + 1:
        raise ValueError(f"se necesitan al menos {degree + 1} puntos para un ajuste de grado {degree}")

    if regions is not None:
        mask = _region_mask(wavelength, regions)
        if not np.any(mask):
            raise ValueError("ninguno de los puntos reales cae dentro de las regiones de continuo indicadas")
    else:
        mask = np.ones(wavelength.size, dtype=bool)

    if method == "spline":
        # arranque robusto: un spline es mucho más flexible localmente que
        # un polinomio de grado bajo, así que ajustarlo directamente sobre
        # puntos todavía sin depurar puede terminar siguiendo un pico
        # aislado en vez de ignorarlo (la condición de suavizado es una
        # suma global, y un solo residuo enorme la puede dominar). Un
        # primer paso polinómico de grado bajo -- mucho menos sensible a
        # un pico local -- da al spline un punto de partida ya limpio de
        # valores atípicos groseros; nunca se usa para el resultado final.
        pilot_degree = min(degree, 3)
        if np.count_nonzero(mask) >= pilot_degree + 1:
            pilot_coeffs = np.polyfit(wavelength[mask], flux[mask], deg=pilot_degree)
            pilot_residuals = flux - np.polyval(pilot_coeffs, wavelength)
            active = pilot_residuals[mask]
            pilot_mad = float(np.median(np.abs(active - np.median(active))))
            pilot_sigma = max(pilot_mad * _MAD_TO_SIGMA, 1e-12)
            if reject == "both":
                pilot_keep = np.abs(pilot_residuals) <= sigma_clip * pilot_sigma
            elif reject == "emission":
                pilot_keep = pilot_residuals <= sigma_clip * pilot_sigma
            else:
                pilot_keep = pilot_residuals >= -sigma_clip * pilot_sigma
            candidate_mask = pilot_keep & mask
            if np.count_nonzero(candidate_mask) >= degree + 1:
                mask = candidate_mask

    coefficients, predict = _fit_continuum_curve(
        wavelength[mask], flux[mask], method=method, degree=degree, spline_smoothing=spline_smoothing
    )

    for _ in range(max_iters):
        coefficients, predict = _fit_continuum_curve(
            wavelength[mask], flux[mask], method=method, degree=degree, spline_smoothing=spline_smoothing
        )
        residuals = flux - predict(wavelength)
        active_residuals = residuals[mask]
        mad = float(np.median(np.abs(active_residuals - np.median(active_residuals))))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-12)

        if reject == "both":
            candidate = np.abs(residuals) <= sigma_clip * sigma
        elif reject == "emission":
            candidate = residuals <= sigma_clip * sigma
        else:
            candidate = residuals >= -sigma_clip * sigma
        new_mask = candidate & (mask if regions is None else _region_mask(wavelength, regions))

        if np.array_equal(new_mask, mask):
            break
        if np.count_nonzero(new_mask) < degree + 1:
            break
        mask = new_mask

    continuum = predict(wavelength)
    rms = float(math.sqrt(np.mean((flux[mask] - continuum[mask]) ** 2)))
    return ContinuumFit(
        coefficients=coefficients,
        continuum=continuum,
        rms_residual=rms,
        n_rejected=int(np.count_nonzero(~mask)),
        used_mask=mask,
        method=method,
    )


def normalize_by_continuum(flux: np.ndarray, continuum_fit: ContinuumFit) -> np.ndarray:
    """Divide `flux` por el continuo ajustado -- el espectro resultante
    tiene continuo ~1.0, con líneas como desviaciones relativas."""
    with np.errstate(divide="ignore", invalid="ignore"):
        return np.where(continuum_fit.continuum != 0, flux / continuum_fit.continuum, np.nan)
