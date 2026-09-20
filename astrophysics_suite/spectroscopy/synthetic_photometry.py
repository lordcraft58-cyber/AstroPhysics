"""Magnitudes fotométricas sintéticas desde un espectro calibrado en
flujo físico (§50) -- magnitud AB (definición matemática exacta de Oke
& Gunn 1983, ApJS 27, 21 -- ningún punto cero inventado) y magnitud
relativa a una estrella de referencia real, a través de una curva de
transmisión de filtro real.

Nunca llama "magnitud" al resultado de una mera normalización (§37/§41,
mismo principio que en todo el proyecto): exige flujo YA calibrado
físicamente (erg/s/cm^2/Angstrom, la misma convención que produce
`fluxcal.calibrate_flux`) -- nunca ADU crudos ni un espectro solo
normalizado a continuo=1, que no es "calibración absoluta".

Ninguna curva de transmisión de filtro se inventa aquí: se carga
siempre de un archivo real de dos columnas (longitud de onda en
Angstrom, transmisión de fotones 0-1) -- el mismo formato que exporta
el SVO Filter Profile Service (http://svo2.cab.inta-csic.es/theory/fps/),
la fuente pública estándar de la comunidad para curvas de filtro reales.
El catálogo interno (`JOHNSON_COUSINS_FILTERS`/`SDSS_FILTERS`) solo
aporta identidad aproximada (nombre/banda/longitud de onda central
típica, valores de sobra publicados) -- nunca la forma exacta de una
curva, que cambiaría el resultado de verdad y que este módulo no puede
verificar de memoria.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import astropy.units as u
import numpy as np

_AB_ZERO_POINT = -48.60
"""Definición EXACTA del sistema de magnitudes AB (Oke & Gunn 1983,
ApJS 27, 21): `m_AB = -2.5*log10(f_nu[erg/s/cm^2/Hz]) - 48.60` -- una
constante matemática de la definición del sistema, no un valor medido
ni una aproximación."""


@dataclass(frozen=True)
class FilterInfo:
    name: str
    band: str
    system: str
    approximate_central_wavelength_angstrom: float
    """Valor de referencia ampliamente publicado (p. ej. Bessell 1990
    para Johnson-Cousins, Doi et al. 2010/SDSS para ugriz) -- solo
    informativo, NUNCA se usa en el cálculo de magnitud en sí, que
    siempre requiere la curva de transmisión real cargada aparte."""
    reference: str = "valores de referencia ampliamente publicados"


JOHNSON_COUSINS_FILTERS: tuple[FilterInfo, ...] = (
    FilterInfo("U", "U", "Johnson", 3600.0),
    FilterInfo("B", "B", "Johnson", 4400.0),
    FilterInfo("V", "V", "Johnson", 5500.0),
    FilterInfo("R", "R", "Cousins", 6400.0),
    FilterInfo("I", "I", "Cousins", 7900.0),
)

SDSS_FILTERS: tuple[FilterInfo, ...] = (
    FilterInfo("u", "u", "SDSS", 3551.0),
    FilterInfo("g", "g", "SDSS", 4686.0),
    FilterInfo("r", "r", "SDSS", 6165.0),
    FilterInfo("i", "i", "SDSS", 7481.0),
    FilterInfo("z", "z", "SDSS", 8931.0),
)
"""Catálogos deliberadamente modestos, misma disciplina que
`line_catalog.py`/`standard_stars.py`: solo identidad, nunca datos
numéricos de precisión que este módulo no puede verificar."""


@dataclass(frozen=True)
class FilterCurve:
    name: str
    wavelength_angstrom: np.ndarray
    transmission: np.ndarray
    """Respuesta de fotones (0-1), la convención por defecto del SVO
    Filter Profile Service para la mayoría de filtros fotométricos."""


def load_filter_curve(path: str, *, name: str | None = None) -> FilterCurve:
    """Carga una curva de transmisión real de un archivo de dos
    columnas (longitud de onda en Å, transmisión) -- formato SVO Filter
    Profile Service. Ordena por longitud de onda creciente (defensivo,
    algunos archivos ya vienen ordenados, otros no)."""
    data = np.loadtxt(path, comments="#")
    if data.ndim != 2 or data.shape[1] < 2:
        raise ValueError(f"{path!r} no tiene el formato de dos columnas (longitud de onda, transmisión) esperado")
    wavelength = data[:, 0].astype(np.float64)
    transmission = data[:, 1].astype(np.float64)
    order = np.argsort(wavelength)
    filter_name = name if name is not None else path
    return FilterCurve(name=filter_name, wavelength_angstrom=wavelength[order], transmission=transmission[order])


def synthetic_effective_f_nu(
    wavelength_angstrom: np.ndarray, flux_lambda_erg_s_cm2_angstrom: np.ndarray, filter_curve: FilterCurve,
) -> float | None:
    """Densidad de flujo efectiva `f_nu` bajo el filtro (fórmula de
    fotones ponderados, Fukugita et al. 1996, AJ 111, 1748):

        f_nu_eff = integral(f_nu(lambda) * R(lambda) / lambda dlambda)
                   / integral(R(lambda) / lambda dlambda)

    `f_lambda -> f_nu` se convierte con `astropy.units.spectral_
    density` (evita cualquier error manual de conversión de unidades).

    Devuelve `None` (nunca extrapola) si el espectro dado no cubre por
    completo el rango de longitud de onda donde el filtro es real, o si
    el flujo efectivo resultante no es positivo (no hay magnitud real
    que dar sobre un flujo neto nulo o negativo)."""
    if wavelength_angstrom.shape != flux_lambda_erg_s_cm2_angstrom.shape:
        raise ValueError("wavelength_angstrom y flux_lambda_erg_s_cm2_angstrom deben tener la misma forma")

    valid = np.isfinite(flux_lambda_erg_s_cm2_angstrom) & np.isfinite(wavelength_angstrom)
    if not np.any(valid):
        return None

    filter_wl = filter_curve.wavelength_angstrom
    covered_lo, covered_hi = float(wavelength_angstrom[valid].min()), float(wavelength_angstrom[valid].max())
    if covered_lo > filter_wl.min() or covered_hi < filter_wl.max():
        return None  # el objeto no cubre el filtro completo -- nunca se extrapola

    flux_on_filter_grid = np.interp(filter_wl, wavelength_angstrom[valid], flux_lambda_erg_s_cm2_angstrom[valid])
    f_nu = (
        (flux_on_filter_grid * (u.erg / u.s / u.cm**2 / u.AA))
        .to(u.erg / u.s / u.cm**2 / u.Hz, equivalencies=u.spectral_density(filter_wl * u.AA))
        .value
    )

    weight = filter_curve.transmission / filter_wl
    denominator = float(np.trapezoid(weight, filter_wl))
    if denominator <= 0:
        raise ValueError(f"la curva de transmisión {filter_curve.name!r} no tiene área positiva bajo la ponderación de fotones")

    f_nu_eff = float(np.trapezoid(f_nu * weight, filter_wl)) / denominator
    return f_nu_eff if f_nu_eff > 0 else None


def ab_magnitude(
    wavelength_angstrom: np.ndarray, flux_lambda_erg_s_cm2_angstrom: np.ndarray, filter_curve: FilterCurve,
) -> float | None:
    """Magnitud AB sintética real -- `None` si `synthetic_effective_
    f_nu` no puede dar un valor real (cobertura incompleta, o flujo
    neto no positivo bajo el filtro)."""
    f_nu_eff = synthetic_effective_f_nu(wavelength_angstrom, flux_lambda_erg_s_cm2_angstrom, filter_curve)
    if f_nu_eff is None:
        return None
    return -2.5 * math.log10(f_nu_eff) + _AB_ZERO_POINT


def relative_magnitude(
    wavelength_angstrom_a: np.ndarray, flux_lambda_a: np.ndarray,
    wavelength_angstrom_b: np.ndarray, flux_lambda_b: np.ndarray,
    filter_curve: FilterCurve,
) -> float | None:
    """`m_a - m_b` bajo el mismo filtro, sin necesitar un punto cero
    absoluto -- útil para comparar contra una estrella de referencia
    real (p. ej. Vega vía `standard_stars.load_calspec_spectrum`, cuya
    magnitud catalogada real el llamador suma aparte si quiere una
    magnitud absoluta en el sistema Vega, en vez de asumirla aquí).
    `None` si cualquiera de los dos flujos efectivos no se puede
    calcular (mismas condiciones que `ab_magnitude`)."""
    f_nu_a = synthetic_effective_f_nu(wavelength_angstrom_a, flux_lambda_a, filter_curve)
    f_nu_b = synthetic_effective_f_nu(wavelength_angstrom_b, flux_lambda_b, filter_curve)
    if f_nu_a is None or f_nu_b is None:
        return None
    return -2.5 * math.log10(f_nu_a / f_nu_b)
