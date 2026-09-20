"""Ajuste paramétrico de perfiles de línea -- Gaussiano, Voigt y multi-
Gaussiano simultáneo (§62), complementario al centroide de momento de
`lines.py` (robusto, sin asumir ninguna forma de perfil, pero SIN
incertidumbre real de centroide -- limitación documentada allí y en
`radial_velocity.py`).

Aquí se asume explícitamente una forma de perfil y se ajusta por
mínimos cuadrados no lineales real (`astropy.modeling.fitting.
LevMarLSQFitter`, la implementación estándar y ya probada de la
comunidad -- no un ajuste propio reinventado), lo que da acceso a una
incertidumbre real por parámetro a partir de la matriz de covarianza
del ajuste.

Mismo convenio de signo que `lines.py`: amplitud negativa = absorción,
positiva = emisión (relativo al continuo ya restado); ancho equivalente
positivo para absorción.

Nunca acepta un ajuste degenerado como una medida real (§62 implícito,
mismo principio que el resto del encargo): un ajuste sin convergencia,
sin matriz de covarianza calculable, o cuya amplitud no supera
`min_significance_sigma` veces su propia incertidumbre (3σ por defecto,
el umbral de detección estándar en espectroscopía) se descarta --
`None`, nunca un número con una fiabilidad que no se puede sostener.

Limitación real conocida, no oculta ("look-elsewhere effect"): como el
centro y el ancho de cada componente son libres dentro de la ventana, el
ajuste busca la MEJOR fluctuación de ruido posible, no una posición fija
-- eso hace que la tasa real de falso positivo a un umbral nominal de 3σ
sea bastante mayor que 3σ de verdad (medido: ~1 de cada 7 ventanas de
puro ruido produce un componente "significativo" en un ajuste de dos
líneas). Para una detección que deba resistir ese efecto, usar un
`min_significance_sigma` más exigente (p. ej. 5) o corroborar contra
`lines.measure_line`/el catálogo de líneas esperadas del objeto.
"""
from __future__ import annotations

import math
import warnings
from dataclasses import dataclass

import numpy as np
from astropy.modeling import fitting, models

_MIN_POINTS_FOR_GAUSSIAN_FIT = 6
"""Al menos el doble de los 3 parámetros libres (amplitud/centro/sigma)
para tener grados de libertad de sobra -- mismo espíritu que
`calibration_provenance.MIN_LINES_PER_DEGREE`."""

_MIN_POINTS_FOR_VOIGT_FIT = 8
"""4 parámetros libres (centro/amplitud/fwhm_L/fwhm_G): el doble más un
margen."""

_FWHM_OVER_SIGMA = 2.0 * math.sqrt(2.0 * math.log(2.0))
"""FWHM = este factor * sigma para un perfil Gaussiano -- constante
matemática exacta, no una aproximación."""

_SQRT_2PI = math.sqrt(2.0 * math.pi)

_DEFAULT_MIN_SIGNIFICANCE = 3.0
"""Umbral de detección estándar en espectroscopía (3σ) -- no un
capricho de este proyecto."""


def spectral_resolution(center_wavelength_angstrom: float, fwhm_angstrom: float) -> float:
    """Poder resolutivo real `R = λ / FWHM` (§32) -- FWHM en longitud de
    onda real (Å), NUNCA en píxeles: confundir dispersión (Å/píxel) con
    resolución (adimensional, λ/FWHM_λ) es exactamente el error que este
    encargo pide evitar. El llamador es responsable de convertir un FWHM
    en píxeles a Å (p. ej. con `wavelength.local_dispersion_at_pixel`)
    antes de llamar a esta función -- aquí no se asume ninguna dispersión.
    """
    if fwhm_angstrom <= 0:
        raise ValueError("fwhm_angstrom debe ser positivo para calcular una resolución real")
    if center_wavelength_angstrom <= 0:
        raise ValueError("center_wavelength_angstrom debe ser positivo")
    return center_wavelength_angstrom / fwhm_angstrom


def _success(fitter) -> bool:
    return fitter.fit_info.get("ierr") in (1, 2, 3, 4)


def _window_mask(wavelength: np.ndarray, flux: np.ndarray, continuum: np.ndarray, lo: float, hi: float) -> np.ndarray:
    return (wavelength >= lo) & (wavelength <= hi) & np.isfinite(flux) & np.isfinite(continuum)


@dataclass(frozen=True)
class GaussianLineFit:
    center_wavelength: float
    center_wavelength_uncertainty: float | None
    amplitude: float
    """Negativo para absorción, positivo para emisión -- mismo convenio
    de signo que `lines.measure_line`."""
    amplitude_uncertainty: float | None
    sigma: float
    sigma_uncertainty: float | None
    fwhm: float
    fwhm_uncertainty: float | None
    integrated_flux: float
    """Integral real de la Gaussiana ajustada (`amplitude * sigma *
    sqrt(2*pi)`), no de los datos crudos -- por eso puede diferir
    ligeramente de `lines.LineMeasurement.integrated_flux`, que integra
    los datos directamente dentro de la ventana."""
    integrated_flux_uncertainty: float | None
    equivalent_width: float | None
    """`None` si el continuo en el centro ajustado no es positivo --
    misma condición que `lines.measure_line`."""
    equivalent_width_uncertainty: float | None
    reduced_chi_square: float | None
    """`None` sin `flux_uncertainty` real -- nunca un chi-cuadrado
    calculado sobre una incertidumbre inventada."""
    n_points: int
    window: tuple[float, float]

    @property
    def significance(self) -> float | None:
        if self.amplitude_uncertainty is None or self.amplitude_uncertainty <= 0:
            return None
        return abs(self.amplitude) / self.amplitude_uncertainty


def _gaussian_derived(
    amplitude: float, stddev: float, amplitude_var: float, stddev_var: float, cov_amp_stddev: float,
    continuum_at_center: float,
) -> tuple[float, float, float, float, float, float, float | None, float | None]:
    """`(fwhm, fwhm_unc, integrated_flux, integrated_flux_unc, amplitude_unc, sigma_unc, ew, ew_unc)`
    -- matemática compartida entre el ajuste de una línea y cada
    componente de un ajuste multi-Gaussiano simultáneo."""
    amplitude_unc = math.sqrt(max(amplitude_var, 0.0))
    sigma_unc = math.sqrt(max(stddev_var, 0.0))
    fwhm = _FWHM_OVER_SIGMA * stddev
    fwhm_unc = _FWHM_OVER_SIGMA * sigma_unc
    integrated_flux = amplitude * stddev * _SQRT_2PI
    integrated_flux_var = (_SQRT_2PI**2) * (
        stddev**2 * amplitude_var + amplitude**2 * stddev_var + 2 * amplitude * stddev * cov_amp_stddev
    )
    integrated_flux_unc = math.sqrt(max(integrated_flux_var, 0.0))
    equivalent_width = None
    equivalent_width_unc = None
    if continuum_at_center > 0:
        equivalent_width = -integrated_flux / continuum_at_center
        equivalent_width_unc = integrated_flux_unc / continuum_at_center
    return fwhm, fwhm_unc, integrated_flux, integrated_flux_unc, amplitude_unc, sigma_unc, equivalent_width, equivalent_width_unc


def fit_gaussian_line(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    *,
    expected_wavelength: float,
    window_halfwidth: float,
    flux_uncertainty: np.ndarray | None = None,
    min_significance_sigma: float = _DEFAULT_MIN_SIGNIFICANCE,
) -> GaussianLineFit | None:
    """Ajusta un perfil Gaussiano real (mínimos cuadrados no lineales,
    `astropy.modeling`) a la línea esperada en
    `[expected_wavelength - window_halfwidth, expected_wavelength + window_halfwidth]`.

    Devuelve `None` (nunca un ajuste inventado) cuando: hay menos de
    `_MIN_POINTS_FOR_GAUSSIAN_FIT` puntos usables en la ventana, la
    ventana no permite acotar `sigma` de forma sensata (menos de dos
    píxeles de separación media), el ajuste no converge, no se puede
    calcular una matriz de covarianza real, o la amplitud ajustada no
    supera `min_significance_sigma` veces su propia incertidumbre.
    """
    if wavelength.shape != flux.shape or wavelength.shape != continuum.shape:
        raise ValueError("wavelength, flux y continuum deben tener la misma forma")
    if flux_uncertainty is not None and flux_uncertainty.shape != flux.shape:
        raise ValueError("flux_uncertainty debe tener la misma forma que flux")
    if window_halfwidth <= 0:
        raise ValueError("window_halfwidth debe ser positivo")
    if min_significance_sigma <= 0:
        raise ValueError("min_significance_sigma debe ser positivo")

    lo, hi = expected_wavelength - window_halfwidth, expected_wavelength + window_halfwidth
    mask = _window_mask(wavelength, flux, continuum, lo, hi)
    n_points = int(np.count_nonzero(mask))
    if n_points < _MIN_POINTS_FOR_GAUSSIAN_FIT:
        return None

    order = np.argsort(wavelength[mask])
    w = wavelength[mask][order]
    c = continuum[mask][order]
    residual = (flux[mask] - continuum[mask])[order]
    unc = flux_uncertainty[mask][order] if flux_uncertainty is not None else None

    median_step = float(np.median(np.abs(np.diff(w)))) if w.size > 1 else window_halfwidth
    min_sigma = max(median_step * 0.5, 1e-9)
    if min_sigma >= window_halfwidth:
        return None  # datos demasiado dispersos frente a la ventana: no hay resolución para un ajuste real

    peak_index = int(np.argmax(np.abs(residual)))
    init = models.Gaussian1D(
        amplitude=float(residual[peak_index]), mean=float(w[peak_index]),
        stddev=float(np.clip(window_halfwidth / 4.0, min_sigma, window_halfwidth)),
        bounds={"mean": (lo, hi), "stddev": (min_sigma, window_halfwidth)},
    )
    fitter = fitting.LevMarLSQFitter(calc_uncertainties=True)
    weights = (1.0 / unc) if unc is not None else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = fitter(init, w, residual, weights=weights, maxiter=500)

    if not _success(fitter) or fitted.cov_matrix is None:
        return None

    cov = fitted.cov_matrix.cov_matrix
    idx = {name: i for i, name in enumerate(fitted.param_names)}
    amplitude, mean, stddev = float(fitted.amplitude.value), float(fitted.mean.value), float(fitted.stddev.value)
    amplitude_var = cov[idx["amplitude"], idx["amplitude"]]
    mean_var = cov[idx["mean"], idx["mean"]]
    stddev_var = cov[idx["stddev"], idx["stddev"]]
    cov_amp_stddev = cov[idx["amplitude"], idx["stddev"]]

    continuum_at_center = float(np.interp(mean, w, c))
    fwhm, fwhm_unc, integrated_flux, integrated_flux_unc, amplitude_unc, sigma_unc, ew, ew_unc = _gaussian_derived(
        amplitude, stddev, amplitude_var, stddev_var, cov_amp_stddev, continuum_at_center
    )

    if amplitude_unc <= 0 or abs(amplitude) < min_significance_sigma * amplitude_unc:
        return None  # no supera el umbral de detección: no es una línea real, es ruido ajustado

    reduced_chi_square = None
    if unc is not None:
        chi_square = float(np.sum(((residual - fitted(w)) / unc) ** 2))
        dof = n_points - len(fitted.param_names)
        if dof > 0:
            reduced_chi_square = chi_square / dof

    return GaussianLineFit(
        center_wavelength=mean, center_wavelength_uncertainty=math.sqrt(max(mean_var, 0.0)),
        amplitude=amplitude, amplitude_uncertainty=amplitude_unc, sigma=stddev, sigma_uncertainty=sigma_unc,
        fwhm=fwhm, fwhm_uncertainty=fwhm_unc, integrated_flux=integrated_flux,
        integrated_flux_uncertainty=integrated_flux_unc, equivalent_width=ew, equivalent_width_uncertainty=ew_unc,
        reduced_chi_square=reduced_chi_square, n_points=n_points, window=(lo, hi),
    )


@dataclass(frozen=True)
class VoigtLineFit:
    center_wavelength: float
    center_wavelength_uncertainty: float | None
    amplitude_lorentzian: float
    """Parámetro `amplitude_L` de `astropy.modeling.models.Voigt1D` --
    negativo para absorción, positivo para emisión."""
    amplitude_lorentzian_uncertainty: float | None
    fwhm_lorentzian: float
    fwhm_lorentzian_uncertainty: float | None
    fwhm_gaussian: float
    fwhm_gaussian_uncertainty: float | None
    fwhm_voigt: float
    """Ancho a media altura del perfil de Voigt combinado -- aproximación
    de Olivero & Longbothum (1977, JQSRT 17, 233), exacta a ~0.02%:
    `fwhm_V = 0.5346*fwhm_L + sqrt(0.2166*fwhm_L^2 + fwhm_G^2)`."""
    integrated_flux: float | None
    """Integral numérica real del perfil AJUSTADO (no de los datos
    crudos) sobre un rango amplio alrededor del centro -- `None` si el
    ajuste no convergió a anchos finitos con los que integrar."""
    equivalent_width: float | None
    reduced_chi_square: float | None
    n_points: int
    window: tuple[float, float]

    @property
    def significance(self) -> float | None:
        if self.amplitude_lorentzian_uncertainty is None or self.amplitude_lorentzian_uncertainty <= 0:
            return None
        return abs(self.amplitude_lorentzian) / self.amplitude_lorentzian_uncertainty


def fit_voigt_line(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    *,
    expected_wavelength: float,
    window_halfwidth: float,
    flux_uncertainty: np.ndarray | None = None,
    min_significance_sigma: float = _DEFAULT_MIN_SIGNIFICANCE,
) -> VoigtLineFit | None:
    """Igual que `fit_gaussian_line` pero con un perfil de Voigt
    (Gaussiana convolucionada con Lorentziana) -- apropiado cuando el
    perfil real tiene alas más anchas que una Gaussiana pura (ensanche
    de presión/Stark, o simplemente una línea que no ajusta bien con
    `fit_gaussian_line`).

    Limitación documentada, no oculta: a diferencia de la Gaussiana, no
    hay una fórmula cerrada simple para propagar la incertidumbre de la
    integral de un perfil de Voigt a partir de la covarianza del ajuste
    -- `integrated_flux`/`equivalent_width` se dan como valores
    centrales reales (integral numérica del modelo ajustado), sin una
    incertidumbre asociada.
    """
    if wavelength.shape != flux.shape or wavelength.shape != continuum.shape:
        raise ValueError("wavelength, flux y continuum deben tener la misma forma")
    if flux_uncertainty is not None and flux_uncertainty.shape != flux.shape:
        raise ValueError("flux_uncertainty debe tener la misma forma que flux")
    if window_halfwidth <= 0:
        raise ValueError("window_halfwidth debe ser positivo")
    if min_significance_sigma <= 0:
        raise ValueError("min_significance_sigma debe ser positivo")

    lo, hi = expected_wavelength - window_halfwidth, expected_wavelength + window_halfwidth
    mask = _window_mask(wavelength, flux, continuum, lo, hi)
    n_points = int(np.count_nonzero(mask))
    if n_points < _MIN_POINTS_FOR_VOIGT_FIT:
        return None

    order = np.argsort(wavelength[mask])
    w = wavelength[mask][order]
    c = continuum[mask][order]
    residual = (flux[mask] - continuum[mask])[order]
    unc = flux_uncertainty[mask][order] if flux_uncertainty is not None else None

    median_step = float(np.median(np.abs(np.diff(w)))) if w.size > 1 else window_halfwidth
    min_fwhm = max(median_step, 1e-9)
    if min_fwhm >= window_halfwidth:
        return None

    peak_index = int(np.argmax(np.abs(residual)))
    fwhm_guess = float(np.clip(window_halfwidth / 3.0, min_fwhm, window_halfwidth))
    init = models.Voigt1D(
        x_0=float(w[peak_index]), amplitude_L=float(residual[peak_index]), fwhm_L=fwhm_guess, fwhm_G=fwhm_guess,
        bounds={"x_0": (lo, hi), "fwhm_L": (min_fwhm, 2 * window_halfwidth), "fwhm_G": (min_fwhm, 2 * window_halfwidth)},
    )
    fitter = fitting.LevMarLSQFitter(calc_uncertainties=True)
    weights = (1.0 / unc) if unc is not None else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = fitter(init, w, residual, weights=weights, maxiter=500)

    if not _success(fitter) or fitted.cov_matrix is None:
        return None

    cov = fitted.cov_matrix.cov_matrix
    idx = {name: i for i, name in enumerate(fitted.param_names)}
    x_0 = float(fitted.x_0.value)
    amplitude_l = float(fitted.amplitude_L.value)
    fwhm_l = float(fitted.fwhm_L.value)
    fwhm_g = float(fitted.fwhm_G.value)
    amplitude_unc = math.sqrt(max(cov[idx["amplitude_L"], idx["amplitude_L"]], 0.0))

    if amplitude_unc <= 0 or abs(amplitude_l) < min_significance_sigma * amplitude_unc:
        return None

    x0_unc = math.sqrt(max(cov[idx["x_0"], idx["x_0"]], 0.0))
    fwhm_l_unc = math.sqrt(max(cov[idx["fwhm_L"], idx["fwhm_L"]], 0.0))
    fwhm_g_unc = math.sqrt(max(cov[idx["fwhm_G"], idx["fwhm_G"]], 0.0))
    fwhm_voigt = 0.5346 * fwhm_l + math.sqrt(0.2166 * fwhm_l**2 + fwhm_g**2)

    integration_half_range = 10.0 * max(fwhm_voigt, min_fwhm)
    fine_grid = np.linspace(x_0 - integration_half_range, x_0 + integration_half_range, 2001)
    integrated_flux = float(np.trapezoid(fitted(fine_grid), fine_grid))
    continuum_at_center = float(np.interp(x_0, w, c))
    equivalent_width = -integrated_flux / continuum_at_center if continuum_at_center > 0 else None

    reduced_chi_square = None
    if unc is not None:
        chi_square = float(np.sum(((residual - fitted(w)) / unc) ** 2))
        dof = n_points - len(fitted.param_names)
        if dof > 0:
            reduced_chi_square = chi_square / dof

    return VoigtLineFit(
        center_wavelength=x_0, center_wavelength_uncertainty=x0_unc,
        amplitude_lorentzian=amplitude_l, amplitude_lorentzian_uncertainty=amplitude_unc,
        fwhm_lorentzian=fwhm_l, fwhm_lorentzian_uncertainty=fwhm_l_unc,
        fwhm_gaussian=fwhm_g, fwhm_gaussian_uncertainty=fwhm_g_unc, fwhm_voigt=fwhm_voigt,
        integrated_flux=integrated_flux, equivalent_width=equivalent_width,
        reduced_chi_square=reduced_chi_square, n_points=n_points, window=(lo, hi),
    )


@dataclass(frozen=True)
class MultiGaussianLineFit:
    components: tuple[GaussianLineFit, ...]
    """Solo los componentes cuya amplitud superó el umbral de
    significancia dentro del ajuste CONJUNTO -- un componente
    insignificante se omite, nunca se informa como una detección real.
    Cada componente lleva el mismo `window`/`n_points`/`reduced_chi_
    square` porque son propiedades del ajuste simultáneo completo, no
    de un componente aislado."""
    n_components_requested: int


def fit_multi_gaussian_lines(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    *,
    expected_wavelengths: tuple[float, ...],
    window_halfwidth: float,
    flux_uncertainty: np.ndarray | None = None,
    shared_sigma: bool = False,
    min_significance_sigma: float = _DEFAULT_MIN_SIGNIFICANCE,
) -> MultiGaussianLineFit | None:
    """Ajuste SIMULTÁNEO de `len(expected_wavelengths)` Gaussianas sobre
    una única ventana compartida que cubre todas las líneas esperadas
    (§62: "ajuste multi-componente simultáneo para dobletes" -- Na D,
    [N II], [S II]) -- cada componente ve la contribución de los demás
    durante el ajuste, a diferencia de ajustar cada línea por separado
    con `fit_gaussian_line`, lo que importa de verdad cuando las líneas
    están parcialmente mezcladas.

    `shared_sigma=True` ata el sigma de todas las componentes al de la
    primera (misma resolución instrumental para líneas próximas) -- una
    hipótesis física explícita que el llamador debe pedir, no un
    comportamiento por defecto oculto.
    """
    if not expected_wavelengths:
        raise ValueError("expected_wavelengths no puede estar vacío")
    if wavelength.shape != flux.shape or wavelength.shape != continuum.shape:
        raise ValueError("wavelength, flux y continuum deben tener la misma forma")
    if flux_uncertainty is not None and flux_uncertainty.shape != flux.shape:
        raise ValueError("flux_uncertainty debe tener la misma forma que flux")
    if window_halfwidth <= 0:
        raise ValueError("window_halfwidth debe ser positivo")

    n_lines = len(expected_wavelengths)
    lo = min(expected_wavelengths) - window_halfwidth
    hi = max(expected_wavelengths) + window_halfwidth
    mask = _window_mask(wavelength, flux, continuum, lo, hi)
    n_points = int(np.count_nonzero(mask))
    if n_points < max(_MIN_POINTS_FOR_GAUSSIAN_FIT, 3 * n_lines):
        return None

    order = np.argsort(wavelength[mask])
    w = wavelength[mask][order]
    c = continuum[mask][order]
    residual = (flux[mask] - continuum[mask])[order]
    unc = flux_uncertainty[mask][order] if flux_uncertainty is not None else None

    median_step = float(np.median(np.abs(np.diff(w)))) if w.size > 1 else window_halfwidth
    min_sigma = max(median_step * 0.5, 1e-9)
    max_sigma = max(window_halfwidth / 2.0, min_sigma * 2)
    if min_sigma >= max_sigma:
        return None

    compound = None
    for wl in expected_wavelengths:
        nearby = np.abs(w - wl) <= window_halfwidth
        amplitude_guess = float(residual[nearby][np.argmax(np.abs(residual[nearby]))]) if np.any(nearby) else float(np.max(np.abs(residual))) * np.sign(residual[np.argmax(np.abs(residual))])
        component = models.Gaussian1D(
            amplitude=amplitude_guess, mean=wl, stddev=float(np.clip(window_halfwidth / 4.0, min_sigma, max_sigma)),
            bounds={"mean": (wl - window_halfwidth, wl + window_halfwidth), "stddev": (min_sigma, max_sigma)},
        )
        compound = component if compound is None else compound + component

    if shared_sigma and n_lines > 1:
        for i in range(1, n_lines):
            getattr(compound, f"stddev_{i}").tied = lambda m: m.stddev_0.value

    fitter = fitting.LevMarLSQFitter(calc_uncertainties=True)
    weights = (1.0 / unc) if unc is not None else None
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fitted = fitter(compound, w, residual, weights=weights, maxiter=1000)

    if not _success(fitter) or fitted.cov_matrix is None:
        return None

    cov = fitted.cov_matrix.cov_matrix
    param_names = fitted.param_names
    free_names = [
        name for name in param_names
        if not getattr(fitted, name).tied and not getattr(fitted, name).fixed
    ]
    free_index = {name: i for i, name in enumerate(free_names)}

    reduced_chi_square = None
    if unc is not None:
        chi_square = float(np.sum(((residual - fitted(w)) / unc) ** 2))
        dof = n_points - len(free_names)
        if dof > 0:
            reduced_chi_square = chi_square / dof

    # `astropy` solo sufija los nombres de parámetro (`amplitude_0`...)
    # cuando de verdad hay un `CompoundModel` -- con una única línea,
    # `compound` sigue siendo un `Gaussian1D` liso con nombres sin sufijo.
    stddev_0_name = "stddev_0" if n_lines > 1 else "stddev"

    def _component_name(base: str, i: int) -> str:
        return f"{base}_{i}" if n_lines > 1 else base

    def _param_var(name: str) -> float:
        if name in free_index:
            i = free_index[name]
            return float(cov[i, i])
        return float(cov[free_index[stddev_0_name], free_index[stddev_0_name]])  # atado -> mismo sigma_0

    def _cov_amp_stddev(amp_name: str, std_name: str) -> float:
        if amp_name in free_index and std_name in free_index:
            return float(cov[free_index[amp_name], free_index[std_name]])
        if amp_name in free_index and std_name not in free_index:  # sigma atado a stddev_0
            return float(cov[free_index[amp_name], free_index[stddev_0_name]])
        return 0.0

    components: list[GaussianLineFit] = []
    for i in range(n_lines):
        amplitude_name, mean_name, stddev_name = _component_name("amplitude", i), _component_name("mean", i), _component_name("stddev", i)
        amplitude = float(getattr(fitted, amplitude_name).value)
        mean = float(getattr(fitted, mean_name).value)
        stddev = float(getattr(fitted, stddev_name).value)
        amplitude_var = _param_var(amplitude_name)
        mean_var = _param_var(mean_name)
        stddev_var = _param_var(stddev_name)
        cov_amp_stddev = _cov_amp_stddev(amplitude_name, stddev_name)
        continuum_at_center = float(np.interp(mean, w, c))
        fwhm, fwhm_unc, integrated_flux, integrated_flux_unc, amplitude_unc, sigma_unc, ew, ew_unc = _gaussian_derived(
            amplitude, stddev, amplitude_var, stddev_var, cov_amp_stddev, continuum_at_center
        )
        if amplitude_unc <= 0 or abs(amplitude) < min_significance_sigma * amplitude_unc:
            continue
        components.append(GaussianLineFit(
            center_wavelength=mean, center_wavelength_uncertainty=math.sqrt(max(mean_var, 0.0)),
            amplitude=amplitude, amplitude_uncertainty=amplitude_unc, sigma=stddev, sigma_uncertainty=sigma_unc,
            fwhm=fwhm, fwhm_uncertainty=fwhm_unc, integrated_flux=integrated_flux,
            integrated_flux_uncertainty=integrated_flux_unc, equivalent_width=ew, equivalent_width_uncertainty=ew_unc,
            reduced_chi_square=reduced_chi_square, n_points=n_points, window=(lo, hi),
        ))

    if not components:
        return None
    return MultiGaussianLineFit(components=tuple(components), n_components_requested=n_lines)
