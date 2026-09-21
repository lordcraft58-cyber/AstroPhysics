"""Velocidad radial (§58/§59/§61): desplazamiento Doppler de una única
línea, combinación multi-línea con dispersión explícita entre líneas
(§59, "nunca confiar en una sola línea"), y correlación cruzada contra
una plantilla (§58) -- siempre como velocidad OBSERVADA/topocéntrica,
distinta de cualquier corrección heliocéntrica/baricéntrica
(`heliocentric.py`, §60), que el llamador aplica después si quiere el
resultado en otro marco de referencia.

Convención de signo estándar de la comunidad: positivo = alejándose
(corrimiento al rojo), negativo = acercándose (corrimiento al azul).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.spectroscopy.line_catalog import SpectralLine
from astrophysics_suite.spectroscopy.lines import LineMeasurement, measure_line

C_KM_S = 299792.458
"""Velocidad de la luz exacta en km/s (definición SI del metro)."""


def velocity_from_wavelength_shift(
    observed_wavelength: np.ndarray | float, rest_wavelength: float, *, relativistic: bool = False
) -> np.ndarray | float:
    """Velocidad radial de línea de visión a partir de un desplazamiento
    Doppler medido -- también sirve para convertir un eje completo de
    longitud de onda a velocidad (§61: pasar un array de `wavelength`).

    - `relativistic=False` (por defecto): fórmula clásica
      `v = c * (lambda_obs / lambda_rest - 1)` -- válida y estándar para
      las velocidades no relativistas (<< c) de este dominio.
    - `relativistic=True`: fórmula relativista de corrimiento Doppler
      longitudinal (relatividad especial),
      `v = c * (R - 1) / (R + 1)` con `R = (lambda_obs / lambda_rest)^2`.

    El encargo pide (§61) declarar siempre qué convención se usa -- por
    eso es un parámetro explícito, nunca una elección oculta.
    """
    if rest_wavelength <= 0:
        raise ValueError("rest_wavelength debe ser positivo")
    ratio = np.asarray(observed_wavelength, dtype=np.float64) / rest_wavelength
    if not relativistic:
        result = (ratio - 1.0) * C_KM_S
    else:
        r_squared = ratio**2
        result = (r_squared - 1.0) / (r_squared + 1.0) * C_KM_S
    return float(result) if np.ndim(result) == 0 else result


@dataclass(frozen=True)
class LineVelocityMeasurement:
    line: SpectralLine
    measurement: LineMeasurement
    velocity_km_s: float
    velocity_uncertainty_km_s: float | None
    """`None` siempre, por ahora: `lines.measure_line` no propaga todavía
    una incertidumbre de centroide (solo de flujo integrado/EW), así que
    no hay una incertidumbre real de velocidad por línea que propagar --
    inventarla violaría el principio del encargo. La fiabilidad de la
    combinación multi-línea se apoya en su lugar en la dispersión REAL
    entre líneas (`MultiLineRVResult.velocity_dispersion_km_s`), no en
    una incertidumbre por línea fabricada."""


@dataclass(frozen=True)
class MultiLineRVResult:
    measurements: tuple[LineVelocityMeasurement, ...]
    """Solo las líneas realmente medidas -- una línea que `measure_line`
    no pudo medir (fuera de rango, sin señal) se omite, nunca se rellena
    con un valor inventado."""
    combined_velocity_km_s: float | None
    """Media de las velocidades por línea -- `None` si ninguna línea se
    pudo medir (`n_lines_used == 0`)."""
    combined_velocity_uncertainty_km_s: float | None
    """Error estándar de la media (`dispersión / sqrt(n)`) -- `None` con
    menos de 2 líneas medidas (no hay dispersión que estimar)."""
    velocity_dispersion_km_s: float | None
    """Desviación estándar (muestral) de las velocidades individuales --
    la señal de fiabilidad explícita que pide el encargo (§59): una
    dispersión grande avisa de una calibración dudosa o una línea mal
    identificada, algo que un único número combinado ocultaría."""
    n_lines_requested: int
    n_lines_used: int

    @property
    def all_lines_measured(self) -> bool:
        return self.n_lines_used == self.n_lines_requested


def measure_multi_line_radial_velocity(
    wavelength: np.ndarray,
    flux: np.ndarray,
    continuum: np.ndarray,
    lines: tuple[SpectralLine, ...],
    *,
    window_halfwidth: float,
    flux_uncertainty: np.ndarray | None = None,
    relativistic: bool = False,
) -> MultiLineRVResult:
    """Mide la velocidad radial independientemente en cada línea dada
    (nunca depende de una sola, §59) y combina las medidas reales en una
    única estimación con su dispersión explícita.

    `lines` es responsabilidad del llamador (p. ej. un subconjunto de
    `line_catalog.BALMER_LINES` apropiado para el tipo espectral del
    objeto) -- este motor no elige qué líneas son "las del objeto".
    """
    measurements: list[LineVelocityMeasurement] = []
    for line in lines:
        result = measure_line(
            wavelength, flux, continuum,
            expected_wavelength=line.wavelength_air_angstrom, window_halfwidth=window_halfwidth,
            flux_uncertainty=flux_uncertainty,
        )
        if result is None:
            continue
        velocity = velocity_from_wavelength_shift(
            result.center_wavelength, line.wavelength_air_angstrom, relativistic=relativistic
        )
        measurements.append(LineVelocityMeasurement(
            line=line, measurement=result, velocity_km_s=float(velocity), velocity_uncertainty_km_s=None,
        ))

    n_used = len(measurements)
    if n_used == 0:
        return MultiLineRVResult(
            measurements=(), combined_velocity_km_s=None, combined_velocity_uncertainty_km_s=None,
            velocity_dispersion_km_s=None, n_lines_requested=len(lines), n_lines_used=0,
        )

    velocities = np.array([m.velocity_km_s for m in measurements])
    combined = float(np.mean(velocities))
    dispersion = float(np.std(velocities, ddof=1)) if n_used > 1 else None
    combined_uncertainty = (dispersion / np.sqrt(n_used)) if dispersion is not None else None

    return MultiLineRVResult(
        measurements=tuple(measurements), combined_velocity_km_s=combined,
        combined_velocity_uncertainty_km_s=combined_uncertainty, velocity_dispersion_km_s=dispersion,
        n_lines_requested=len(lines), n_lines_used=n_used,
    )


@dataclass(frozen=True)
class CrossCorrelationRVResult:
    velocities_km_s: np.ndarray
    correlation: np.ndarray
    """`NaN` en las velocidades de prueba sin solape útil entre plantilla
    y observado -- una correlación 0.0 real (formas realmente
    descorrelacionadas) y una ausencia de solape son datos distintos, y
    tratarlos igual escondería justo lo que hace fiable o no el pico."""
    best_velocity_km_s: float
    peak_correlation: float
    n_overlap_points: int
    """Nº de puntos realmente solapados en la velocidad de mejor ajuste
    -- un pico apoyado en pocos puntos es sospechoso aunque sea alto."""


def cross_correlate_radial_velocity(
    observed_wavelength: np.ndarray,
    observed_flux_normalized: np.ndarray,
    template_wavelength: np.ndarray,
    template_flux_normalized: np.ndarray,
    *,
    velocity_min_km_s: float = -500.0,
    velocity_max_km_s: float = 500.0,
    velocity_step_km_s: float = 1.0,
    min_overlap_points: int = 10,
) -> CrossCorrelationRVResult:
    """Correlación cruzada por búsqueda directa en rejilla de velocidad
    (no basada en FFT/rejilla log-lambda -- suficiente para los rangos
    de búsqueda de este dominio, ver limitación documentada más abajo)
    entre un espectro observado y una plantilla de referencia.

    Ambos deben venir YA continuo-normalizados y con cualquier región
    telúrica/no deseada ya enmascarada (`NaN`) por el llamador (§58: esa
    preparación es responsabilidad explícita de quien llama, este motor
    no normaliza ni enmascara nada en silencio).

    Para cada velocidad de prueba `v`, se interpola la plantilla sobre
    la rejilla observada bajo el corrimiento Doppler que `v` implicaría
    y se mide la correlación de Pearson dentro del solape real -- nunca
    extrapolando más allá de los datos reales de ninguna de las dos
    (`np.interp` con `left=right=nan`).

    Limitación conocida, documentada en vez de ocultada: esta es una
    búsqueda en rejilla directa, no la técnica FFT/log-lambda que usan
    los pipelines profesionales de alta precisión -- adecuada para el
    rango y la resolución típicos de este dominio (espectroscopía de
    aficionado/telescopio pequeño), no para velocidades sub-km/s de
    precisión profesional.
    """
    if observed_wavelength.shape != observed_flux_normalized.shape:
        raise ValueError("observed_wavelength y observed_flux_normalized deben tener la misma forma")
    if template_wavelength.shape != template_flux_normalized.shape:
        raise ValueError("template_wavelength y template_flux_normalized deben tener la misma forma")
    if velocity_step_km_s <= 0:
        raise ValueError("velocity_step_km_s debe ser positivo")
    if velocity_max_km_s <= velocity_min_km_s:
        raise ValueError("velocity_max_km_s debe ser mayor que velocity_min_km_s")

    velocities = np.arange(velocity_min_km_s, velocity_max_km_s + velocity_step_km_s, velocity_step_km_s)
    correlation = np.full(velocities.shape, np.nan)
    n_overlap = np.zeros(velocities.shape, dtype=np.int64)

    valid_observed = np.isfinite(observed_flux_normalized)
    obs_mean = float(np.mean(observed_flux_normalized[valid_observed])) if np.any(valid_observed) else 0.0
    obs_centered = np.where(valid_observed, observed_flux_normalized - obs_mean, np.nan)

    for i, v in enumerate(velocities):
        # Bajo una velocidad de prueba v, un píxel observado a
        # lambda_obs corresponde a la longitud de onda en reposo
        # lambda_obs / (1 + v/c) dentro de la plantilla.
        rest_frame_wavelength = observed_wavelength / (1.0 + v / C_KM_S)
        template_at_v = np.interp(
            rest_frame_wavelength, template_wavelength, template_flux_normalized, left=np.nan, right=np.nan
        )
        valid = np.isfinite(template_at_v) & np.isfinite(obs_centered)
        n_valid = int(np.count_nonzero(valid))
        n_overlap[i] = n_valid
        if n_valid < min_overlap_points:
            continue
        obs_sample = obs_centered[valid]
        tmpl_sample = template_at_v[valid] - np.mean(template_at_v[valid])
        obs_std = float(np.std(obs_sample))
        tmpl_std = float(np.std(tmpl_sample))
        if obs_std <= 0 or tmpl_std <= 0:
            continue
        correlation[i] = float(np.mean(obs_sample * tmpl_sample) / (obs_std * tmpl_std))

    if np.all(np.isnan(correlation)):
        raise ValueError(
            f"ninguna velocidad de prueba en [{velocity_min_km_s}, {velocity_max_km_s}] km/s alcanza "
            f"{min_overlap_points} puntos de solape útil -- ¿observado y plantilla cubren el mismo "
            "rango de longitud de onda?"
        )

    peak_index = int(np.nanargmax(correlation))
    best_velocity = float(velocities[peak_index])
    # Refinamiento subpíxel por interpolación parabólica -- mismo estilo
    # numérico que wavelength.reidentify_wavelength_solution.
    if 0 < peak_index < len(velocities) - 1 and np.isfinite(correlation[peak_index - 1]) and np.isfinite(correlation[peak_index + 1]):
        y_left, y_center, y_right = correlation[peak_index - 1], correlation[peak_index], correlation[peak_index + 1]
        denominator = y_left - 2 * y_center + y_right
        if denominator != 0:
            fraction = float(np.clip(0.5 * (y_left - y_right) / denominator, -1.0, 1.0))
            best_velocity += fraction * velocity_step_km_s

    return CrossCorrelationRVResult(
        velocities_km_s=velocities, correlation=correlation, best_velocity_km_s=best_velocity,
        peak_correlation=float(correlation[peak_index]), n_overlap_points=int(n_overlap[peak_index]),
    )
