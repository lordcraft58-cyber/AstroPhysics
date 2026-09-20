"""Extracción de traza espectral -- equivalente propio de `apall` de
IRAF: localizar el rastro espacial de la fuente a lo largo del eje de
dispersión, y extraer un espectro 1D de la imagen 2D por suma simple o
por extracción óptima (Horne 1986, PASP 98, 609).

Convención fija: eje 0 (filas) = espacial, eje 1 (columnas) = dispersión
-- transponer antes de llamar si la imagen viene orientada al revés.

**Contrato de píxeles inválidos** (ver también `frame2d.py`): un píxel
NaN/Inf o marcado como malo en `mask` NUNCA se trata como flujo real, y
una columna que no puede medirse NUNCA se rellena con `0.0`. Se marca
`valid[col] = False` y `flux[col] = NaN`. Este es el arreglo directo de
un hallazgo real con espectros de Vega del usuario: la versión anterior
inicializaba `flux = np.zeros(...)` y dejaba ese 0.0 sin sobrescribir en
cualquier columna donde la ventana de extracción cayera fuera de la
imagen o el denominador de la extracción óptima fuera <= 0 -- un 0.0 es
un valor de flujo perfectamente válido para cualquier consumidor
posterior (el visor `qt_app/spectroscopy/spectrum_view.py` YA estaba
preparado para saltar huecos `NaN` en el trazado, `_build_path`, pero
nunca los recibía: recibía ceros con apariencia de dato real, que se
dibujaban como profundas caídas verticales -- exactamente el síntoma
reportado). Ver docs/audit/55-... para la validación completa.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

_MAD_TO_SIGMA = 1.4826


def _combined_bad(data: np.ndarray, mask: np.ndarray | None) -> np.ndarray:
    """Píxeles a excluir: no finitos SIEMPRE, más lo que diga `mask`
    (`True` = malo) si se da. `mask` puede ser una máscara de bits
    (`frame2d.PixelFlag`, != 0 es malo) o ya booleana."""
    bad = ~np.isfinite(data)
    if mask is not None:
        mask_arr = np.asarray(mask)
        bad = bad | (mask_arr.astype(bool) if mask_arr.dtype == bool else (mask_arr != 0))
    return bad


@dataclass(frozen=True)
class TraceResult:
    columns: np.ndarray
    """Índices de columna (dispersión) cubiertos por la traza."""
    center_px: np.ndarray
    """Centro espacial (fila, subpíxel) ajustado en cada columna."""
    fit_degree: int
    rms_residual_px: float
    n_columns_used_for_fit: int = 0
    """Cuántas columnas tenían un centroide medible y sobrevivieron al
    rechazo iterativo -- si es mucho menor que `len(columns)`, el ajuste
    se apoya en poca evidencia real y el RMS puede no ser representativo."""


def trace_spectrum(
    data: np.ndarray,
    *,
    initial_center_px: float,
    mask: np.ndarray | None = None,
    search_half_width: float = 8.0,
    fit_degree: int = 3,
    sigma_clip: float = 3.0,
    max_iters: int = 5,
) -> TraceResult:
    """Sigue el centroide ponderado por flujo columna a columna (una
    ventana de búsqueda alrededor de la posición de la columna anterior,
    para no perder la traza si el objeto se curva o se inclina), y ajusta
    un polinomio suave con rechazo iterativo de columnas ruidosas
    (rayos cósmicos, columnas sin señal) -- el resultado es el centro de
    extracción que usan `extract_sum`/`extract_optimal`.

    `mask`, si se da (misma forma que `data`, bits `PixelFlag` o
    booleana), excluye esos píxeles del centroide -- además de excluir
    SIEMPRE los no finitos, con o sin `mask`. Antes, una sola columna con
    un NaN dentro de la ventana de búsqueda hacía que `total_weight`
    resultara `NaN` (la comparación `NaN <= 0` es `False` en Python/numpy,
    así que el guardia que debía saltar la columna nunca se disparaba) y
    la función terminaba lanzando `ValueError: cannot convert float NaN
    to integer` en la siguiente columna, al intentar redondear un centro
    de búsqueda ya contaminado -- un cierre en seco de todo el trazado
    por un solo píxel defectuoso.
    """
    if data.ndim != 2:
        raise ValueError("trace_spectrum opera sobre imágenes 2D (espacial x dispersión)")
    height, n_columns = data.shape
    if not (0 <= initial_center_px < height):
        raise ValueError("initial_center_px debe caer dentro de la imagen")
    bad = _combined_bad(data, mask)

    centers = np.full(n_columns, np.nan)
    current_center = initial_center_px
    for col in range(n_columns):
        row_lo = max(0, int(round(current_center - search_half_width)))
        row_hi = min(height, int(round(current_center + search_half_width)) + 1)
        window = data[row_lo:row_hi, col]
        window_bad = bad[row_lo:row_hi, col]
        if np.all(window_bad):
            continue  # ninguna evidencia usable en esta columna: se deja NaN y NO se mueve current_center
        good_window = np.where(window_bad, np.nan, window)
        floor = np.nanpercentile(good_window, 10)
        weights = np.where(window_bad, 0.0, np.clip(window - floor, a_min=0.0, a_max=None))
        total_weight = float(np.sum(weights))
        if total_weight <= 0:
            continue
        rows = np.arange(row_lo, row_hi)
        centroid = float(np.sum(rows * weights) / total_weight)
        centers[col] = centroid
        current_center = centroid

    valid = ~np.isnan(centers)
    if np.count_nonzero(valid) < fit_degree + 1:
        raise ValueError("no hay suficientes columnas con señal usable para ajustar la traza")

    columns_all = np.arange(n_columns)
    columns, values = columns_all[valid], centers[valid]

    for _ in range(max_iters):
        coeffs = np.polyfit(columns, values, deg=fit_degree)
        residuals = values - np.polyval(coeffs, columns)
        mad = float(np.median(np.abs(residuals)))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-6)
        keep = np.abs(residuals) <= sigma_clip * sigma
        if np.all(keep) or np.count_nonzero(keep) < fit_degree + 1:
            break
        columns, values = columns[keep], values[keep]

    coeffs = np.polyfit(columns, values, deg=fit_degree)
    fitted_all = np.polyval(coeffs, columns_all)
    rms = float(math.sqrt(np.mean((values - np.polyval(coeffs, columns)) ** 2)))

    return TraceResult(
        columns=columns_all, center_px=fitted_all, fit_degree=fit_degree, rms_residual_px=rms,
        n_columns_used_for_fit=int(columns.size),
    )


_SKY_REDUCERS = ("median", "mean", "sigma_clip")


@dataclass(frozen=True)
class SkyWindow:
    """Región de cielo independiente de la apertura del objeto (§5):
    un offset y un semiancho respecto al centro de la traza en esa
    columna, no una fila fija -- sigue la curvatura de la traza igual
    que la propia apertura del objeto."""

    offset_px: float
    half_width_px: float


DEFAULT_SKY_WINDOWS = (SkyWindow(offset_px=-10.0, half_width_px=4.0), SkyWindow(offset_px=10.0, half_width_px=4.0))


@dataclass(frozen=True)
class SkyEstimate:
    level: np.ndarray
    """Nivel de cielo por columna, `NaN` donde no se pudo medir --
    nunca `0.0` como relleno silencioso."""
    valid: np.ndarray
    """`True` por columna si hubo al menos un píxel de cielo utilizable."""
    n_pixels_used: np.ndarray
    reducer: str


def _smooth_sky_estimate(
    level: np.ndarray, valid: np.ndarray, n_used: np.ndarray, reducer: str, *, degree: int, sigma_clip: float,
    max_iters: int = 5,
) -> SkyEstimate:
    """Ajuste polinómico suave del cielo YA estimado por columna (§5:
    "ajuste polinómico suave explícito") -- mismo patrón de rechazo
    iterativo sigma-clip ya usado para la traza en `trace_spectrum`,
    reutilizado aquí en vez de reimplementado. Un ajuste real puede
    interpolar sobre columnas donde la estimación directa no tenía
    evidencia (`valid[col] == False`), así que el resultado queda válido
    en toda la traza -- `n_pixels_used` sigue contando solo la evidencia
    real por columna, nunca se rellena."""
    n_columns = level.size
    columns_all = np.arange(n_columns)
    columns, values = columns_all[valid], level[valid]
    if columns.size < degree + 1:
        raise ValueError(
            f"solo {columns.size} columna(s) con cielo real medible -- se necesitan al menos {degree + 1} "
            f"para un ajuste polinómico suave de grado {degree}"
        )
    for _ in range(max_iters):
        coeffs = np.polyfit(columns, values, deg=degree)
        residuals = values - np.polyval(coeffs, columns)
        mad = float(np.median(np.abs(residuals)))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-9)
        keep = np.abs(residuals) <= sigma_clip * sigma
        if np.all(keep) or np.count_nonzero(keep) < degree + 1:
            break
        columns, values = columns[keep], values[keep]
    coeffs = np.polyfit(columns, values, deg=degree)
    smoothed = np.polyval(coeffs, columns_all)
    return SkyEstimate(
        level=smoothed, valid=np.ones(n_columns, dtype=bool), n_pixels_used=n_used, reducer=f"{reducer}+poly(deg={degree})",
    )


def estimate_sky_background(
    data: np.ndarray,
    trace: TraceResult,
    *,
    mask: np.ndarray | None = None,
    windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    reducer: str = "median",
    sigma_clip: float = 3.0,
    smooth_degree: int | None = None,
    smooth_sigma_clip: float = 3.0,
) -> SkyEstimate:
    """Estima el cielo `sky(x)` a partir de regiones EXPLÍCITAS a ambos
    lados de la traza (§5) -- no una única mediana de "lo que quede" en
    torno a la apertura, como hacía la versión anterior
    (`_background_per_column`).

    `reducer`: `"median"` (robusta a un resto de fuente contaminando
    una ventana), `"mean"`, o `"sigma_clip"` (mediana con rechazo
    iterativo de valores atípicos, `sigma_clip` sigmas robustas).

    Si ninguna ventana aporta un solo píxel utilizable en una columna
    (todas fuera de la imagen, o todas marcadas como malas), esa columna
    queda `valid[col] = False` y `level[col] = NaN` -- restar un cielo
    de `0.0` inventado sería peor que no restar nada.

    `smooth_degree`: si se da (no `None`), el nivel de cielo por columna
    ya estimado se suaviza con un ajuste polinómico real de ese grado
    (§5) -- reduce el ruido columna a columna y puede rellenar columnas
    sin evidencia directa con un valor real interpolado, en vez de dejar
    el cielo tal cual salió de cada columna independiente.
    """
    if reducer not in _SKY_REDUCERS:
        raise ValueError(f"reducer debe ser uno de {_SKY_REDUCERS}, recibido {reducer!r}")
    height, n_columns = data.shape
    bad = _combined_bad(data, mask)

    level = np.full(n_columns, np.nan)
    valid = np.zeros(n_columns, dtype=bool)
    n_used = np.zeros(n_columns, dtype=np.int64)

    for col in range(n_columns):
        center = trace.center_px[col]
        samples: list[np.ndarray] = []
        for window in windows:
            lo = max(0, int(round(center + window.offset_px - window.half_width_px)))
            hi = min(height, int(round(center + window.offset_px + window.half_width_px)) + 1)
            if hi <= lo:
                continue
            column_bad = bad[lo:hi, col]
            column_values = data[lo:hi, col]
            good = column_values[~column_bad]
            if good.size:
                samples.append(good)
        if not samples:
            continue
        pool = np.concatenate(samples)
        if reducer == "sigma_clip":
            working = pool
            for _ in range(5):
                med = np.median(working)
                mad = _MAD_TO_SIGMA * np.median(np.abs(working - med))
                if mad <= 0:
                    break
                keep = np.abs(working - med) <= sigma_clip * mad
                if np.all(keep) or np.count_nonzero(keep) == 0:
                    break
                working = working[keep]
            pool = working
        level[col] = float(np.mean(pool)) if reducer == "mean" else float(np.median(pool))
        valid[col] = True
        n_used[col] = int(pool.size)

    if smooth_degree is not None:
        return _smooth_sky_estimate(level, valid, n_used, reducer, degree=smooth_degree, sigma_clip=smooth_sigma_clip)
    return SkyEstimate(level=level, valid=valid, n_pixels_used=n_used, reducer=reducer)


@dataclass(frozen=True)
class ExtractedSpectrum:
    flux: np.ndarray
    """`NaN` en cualquier columna que no se pudo medir -- nunca `0.0`
    como relleno silencioso (ver docstring del módulo)."""
    flux_uncertainty: np.ndarray
    background_per_pixel: np.ndarray
    method: str
    valid: np.ndarray = field(default_factory=lambda: np.array([], dtype=bool))
    """`True` por columna si `flux[col]` es una medida real."""
    n_pixels_used: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))
    """Cuántos píxeles de la apertura contribuyeron de verdad a
    `flux[col]` (excluidos los marcados como malos)."""
    n_pixels_rejected: np.ndarray = field(default_factory=lambda: np.array([], dtype=np.int64))
    sky: SkyEstimate | None = None

    @property
    def n_columns_invalid(self) -> int:
        return int(np.count_nonzero(~self.valid)) if self.valid.size else 0


def extract_sum(
    data: np.ndarray,
    uncertainty: np.ndarray,
    trace: TraceResult,
    *,
    mask: np.ndarray | None = None,
    aperture_half_width: float = 4.0,
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    sky_reducer: str = "median",
    min_valid_fraction: float = 0.3,
    sky_smooth_degree: int | None = None,
    sky_smooth_sigma_clip: float = 3.0,
) -> ExtractedSpectrum:
    """Extracción por suma simple en una ventana espacial que SIGUE la
    traza (`trace.center_px`, no una fila fija), con fondo local estimado
    en regiones de cielo independientes (equivalente al modo `sum` de
    `apall`).

    Los píxeles marcados en `mask` (o no finitos) se EXCLUYEN de la suma
    -- no se cuentan como flujo cero, y no hacen que la columna entera se
    descarte salvo que queden por debajo de `min_valid_fraction` de la
    apertura nominal, en cuyo caso la columna se marca inválida en vez de
    reportar un flujo sesgado por una apertura efectiva mucho más
    pequeña que la nominal sin decirlo.

    `sky_smooth_degree`: ver `estimate_sky_background` (§5) -- se pasa
    tal cual, sin ninguna lógica adicional aquí.
    """
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    height, n_columns = data.shape
    bad = _combined_bad(data, mask)
    sky = estimate_sky_background(
        data, trace, mask=mask, windows=sky_windows, reducer=sky_reducer,
        smooth_degree=sky_smooth_degree, smooth_sigma_clip=sky_smooth_sigma_clip,
    )

    flux = np.full(n_columns, np.nan)
    flux_unc = np.full(n_columns, np.nan)
    valid = np.zeros(n_columns, dtype=bool)
    n_used = np.zeros(n_columns, dtype=np.int64)
    n_rejected = np.zeros(n_columns, dtype=np.int64)
    nominal_pixels = 2 * aperture_half_width + 1

    for col in range(n_columns):
        center = trace.center_px[col]
        lo = max(0, int(round(center - aperture_half_width)))
        hi = min(height, int(round(center + aperture_half_width)) + 1)
        if hi <= lo:
            continue
        column_bad = bad[lo:hi, col]
        good = ~column_bad
        n_good = int(np.count_nonzero(good))
        n_rejected[col] = int(np.count_nonzero(column_bad))
        n_used[col] = n_good
        if n_good == 0 or n_good < min_valid_fraction * nominal_pixels or not sky.valid[col]:
            continue
        # renormalizado por la fracción de apertura realmente medida --
        # una apertura parcialmente enmascarada no debe verse más tenue
        # solo por eso.
        raw_sum = float(np.sum(data[lo:hi, col][good]))
        scale = nominal_pixels / n_good
        flux[col] = raw_sum * scale - sky.level[col] * nominal_pixels
        flux_unc[col] = math.sqrt(float(np.sum(uncertainty[lo:hi, col][good] ** 2))) * scale
        valid[col] = True

    return ExtractedSpectrum(
        flux=flux, flux_uncertainty=flux_unc, background_per_pixel=sky.level, method="sum",
        valid=valid, n_pixels_used=n_used, n_pixels_rejected=n_rejected, sky=sky,
    )


def extract_mean(
    data: np.ndarray,
    uncertainty: np.ndarray,
    trace: TraceResult,
    *,
    mask: np.ndarray | None = None,
    aperture_half_width: float = 4.0,
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    sky_reducer: str = "median",
    min_valid_fraction: float = 0.3,
    sky_smooth_degree: int | None = None,
    sky_smooth_sigma_clip: float = 3.0,
) -> ExtractedSpectrum:
    """Extracción por promedio (§3: modo `average` de `apall`) --
    reutiliza `extract_sum` al 100% y solo reescala su flujo/incertidumbre
    ya calculados por el ancho nominal de la apertura (flujo TOTAL ->
    flujo MEDIO por píxel de apertura), nunca recalcula la extracción
    desde cero: es exactamente la misma suma ya renormalizada por
    apertura parcial, dividida por el ancho nominal completo."""
    summed = extract_sum(
        data, uncertainty, trace, mask=mask, aperture_half_width=aperture_half_width,
        sky_windows=sky_windows, sky_reducer=sky_reducer, min_valid_fraction=min_valid_fraction,
        sky_smooth_degree=sky_smooth_degree, sky_smooth_sigma_clip=sky_smooth_sigma_clip,
    )
    nominal_pixels = 2 * aperture_half_width + 1
    return ExtractedSpectrum(
        flux=summed.flux / nominal_pixels, flux_uncertainty=summed.flux_uncertainty / nominal_pixels,
        background_per_pixel=summed.background_per_pixel, method="mean",
        valid=summed.valid, n_pixels_used=summed.n_pixels_used, n_pixels_rejected=summed.n_pixels_rejected,
        sky=summed.sky,
    )


def extract_optimal(
    data: np.ndarray,
    uncertainty: np.ndarray,
    trace: TraceResult,
    *,
    mask: np.ndarray | None = None,
    aperture_half_width: float = 4.0,
    sky_windows: tuple[SkyWindow, ...] = DEFAULT_SKY_WINDOWS,
    sky_reducer: str = "median",
    min_valid_fraction: float = 0.3,
    sky_smooth_degree: int | None = None,
    sky_smooth_sigma_clip: float = 3.0,
) -> ExtractedSpectrum:
    """Extracción óptima (Horne 1986): construye un perfil espacial
    normalizado compartido -- la mediana, columna a columna, del perfil
    ya normalizado a suma 1 (robusta frente a rayos cósmicos residuales
    en columnas individuales) -- y pondera cada píxel por
    `perfil / varianza` en vez de darle a todos el mismo peso. Maximiza
    la S/N para una fuente débil frente a la extracción por suma simple,
    exactamente el resultado que motiva el método (Horne 1986, sección 2).

    Igual que `extract_sum`: los píxeles marcados se excluyen del perfil
    y de la suma ponderada, y una columna sin evidencia suficiente queda
    `valid=False` con `flux=NaN`, nunca `0.0`. `sky_smooth_degree`: ver
    `estimate_sky_background` (§5).
    """
    if data.shape != uncertainty.shape:
        raise ValueError("data y uncertainty deben tener la misma forma")
    height, n_columns = data.shape
    bad = _combined_bad(data, mask)
    sky = estimate_sky_background(
        data, trace, mask=mask, windows=sky_windows, reducer=sky_reducer,
        smooth_degree=sky_smooth_degree, smooth_sigma_clip=sky_smooth_sigma_clip,
    )

    half = int(round(aperture_half_width))
    window_size = 2 * half + 1
    profiles = np.full((n_columns, window_size), np.nan)

    for col in range(n_columns):
        center_row = int(round(trace.center_px[col]))
        lo, hi = center_row - half, center_row + half + 1
        if lo < 0 or hi > height or not sky.valid[col]:
            continue
        column_bad = bad[lo:hi, col]
        column_values = np.where(column_bad, np.nan, data[lo:hi, col] - sky.level[col])
        total = np.nansum(column_values)
        if total > 0 and np.count_nonzero(~column_bad) >= min_valid_fraction * window_size:
            profiles[col] = np.clip(np.nan_to_num(column_values / total, nan=0.0), a_min=0.0, a_max=None)

    valid_columns = ~np.all(np.isnan(profiles), axis=1)
    if not np.any(valid_columns):
        raise ValueError("no se pudo construir un perfil espacial válido (sin señal usable en la traza)")
    master_profile = np.nanmedian(profiles[valid_columns], axis=0)
    master_profile = np.clip(master_profile, a_min=0.0, a_max=None)
    profile_sum = np.sum(master_profile)
    if profile_sum <= 0:
        raise ValueError("no se pudo construir un perfil espacial válido (sin señal en la traza)")
    master_profile = master_profile / profile_sum

    flux = np.full(n_columns, np.nan)
    flux_unc = np.full(n_columns, np.nan)
    valid = np.zeros(n_columns, dtype=bool)
    n_used = np.zeros(n_columns, dtype=np.int64)
    n_rejected = np.zeros(n_columns, dtype=np.int64)

    for col in range(n_columns):
        center_row = int(round(trace.center_px[col]))
        lo, hi = center_row - half, center_row + half + 1
        if lo < 0 or hi > height or not sky.valid[col]:
            continue
        column_bad = bad[lo:hi, col]
        n_good = int(np.count_nonzero(~column_bad))
        n_rejected[col] = int(np.count_nonzero(column_bad))
        n_used[col] = n_good
        if n_good < min_valid_fraction * window_size:
            continue
        column_values = data[lo:hi, col] - sky.level[col]
        variance = np.clip(uncertainty[lo:hi, col] ** 2, a_min=1e-12, a_max=None)
        profile_here = np.where(column_bad, 0.0, master_profile)
        weights = profile_here / variance
        denominator = float(np.sum(profile_here * weights))
        if denominator <= 0:
            continue
        flux[col] = float(np.sum(weights * np.where(column_bad, 0.0, column_values))) / denominator
        flux_unc[col] = math.sqrt(1.0 / denominator)
        valid[col] = True

    return ExtractedSpectrum(
        flux=flux, flux_uncertainty=flux_unc, background_per_pixel=sky.level, method="optimal",
        valid=valid, n_pixels_used=n_used, n_pixels_rejected=n_rejected, sky=sky,
    )
