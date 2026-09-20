"""Núcleo real de detección de fuentes puntuales: DAOStarFinder
(`photutils`) como algoritmo primario, con un detector robusto propio en
Python puro como reserva verificable cuando `DAOStarFinder` falla en
tiempo real sobre datos concretos -- nunca una lista vacía silenciosa
por una excepción no capturada.

Incluye también el enriquecimiento por fuente (FWHM, elipticidad,
nitidez, S/N de pico, saturación) vía momentos de segundo orden --
métricas locales auditables, independientes de cualquier catálogo
externo (Gaia/SIMBAD).

Migrado de `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.detect_point_sources`
/ `_detect_point_sources_legacy` / `enrich_star_rows`
(docs/audit/54-CIERRE-DETECTION.md). Comportamiento observable
conservado byte a byte, con UNA diferencia deliberada y documentada:
`enrich_detections` corrige la fórmula de FWHM de `enrich_star_rows`
(`2.3548*sqrt(l1*l2)` -- unidades de px^4, nunca fue un FWHM real -- ver
el comentario junto al cálculo, más abajo). `tests/regression/
test_detection_matches_legacy.py` compara campo a campo, fuente a
fuente, contra la implementación original, salvo en ese único campo,
donde en su lugar demuestra la relación exacta con el valor legacy y
con una gaussiana sintética de sigma conocido.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass

import numpy as np
from photutils.detection import DAOStarFinder
from scipy import ndimage as ndi

from astrophysics_suite.detection.background import Background

logger = logging.getLogger(__name__)

# Rangos de forma de DAOStarFinder -- mismos valores que el motor
# original: nitidez (sharpness) y redondez (roundness) esperadas de una
# PSF estelar real, no de un rayo cósmico (muy nítido) ni de un defecto
# extendido (poco nítido / muy alargado).
DAO_SHARPLO = 0.30
DAO_SHARPHI = 0.90
DAO_ROUNDLO = -0.50
DAO_ROUNDHI = 0.50

_FWHM_TO_SIGMA = 2.354820045  # 2*sqrt(2*ln(2))


def _dao_column(table, wanted: str) -> str | None:
    """Busca una columna de una tabla de `photutils` sin distinguir
    mayúsculas y con alias seguros por versión.

    `photutils >= 1.13` renombró `xcentroid`/`ycentroid` a
    `x_centroid`/`y_centroid` en las tablas de `DAOStarFinder`
    (verificado con la versión 3.0.0 realmente instalada en este
    entorno: la tabla trae `x_centroid`/`y_centroid`, no `xcentroid`).
    Sin este alias, cualquier instalación con un `photutils` reciente no
    encuentra la columna y cae siempre al detector de reserva, mucho más
    lento en imágenes reales -- silenciosamente, sin que nada lo avise
    salvo un aviso en el registro fácil de pasar por alto.
    """
    if table is None or not hasattr(table, "colnames"):
        return None
    names = list(table.colnames)
    lower_to_real = {str(n).lower(): n for n in names}
    if wanted.lower() in lower_to_real:
        return lower_to_real[wanted.lower()]
    aliases = {
        "xcentroid": ("xcentroid", "x_centroid", "x_peak", "xpos", "x"),
        "ycentroid": ("ycentroid", "y_centroid", "y_peak", "ypos", "y"),
        "flux": ("flux", "source_flux"),
    }
    for alias in aliases.get(wanted, (wanted,)):
        if alias.lower() in lower_to_real:
            return lower_to_real[alias.lower()]
    return None


def _find_point_sources_dao(
    data: np.ndarray, background: Background, *, fwhm_px: float, threshold_sigma: float, max_sources: int
) -> np.ndarray:
    image = np.asarray(data, np.float32) - np.asarray(background.bkg, np.float32)
    image = np.where(np.isfinite(image), image, 0.0)
    rms_median = float(np.nanmedian(np.asarray(background.rms, np.float32)))
    threshold = float(threshold_sigma) * max(rms_median, 1e-9)
    try:
        # API moderna de photutils (>= 2.x, verificada con 3.0.0).
        finder = DAOStarFinder(
            fwhm=float(fwhm_px), threshold=threshold,
            sharpness_range=(DAO_SHARPLO, DAO_SHARPHI),
            roundness_range=(DAO_ROUNDLO, DAO_ROUNDHI),
            exclude_border=True,
        )
    except TypeError:
        # API de versiones más antiguas de photutils (>= 1.13, el mínimo
        # que declara requirements-app.txt/requirements-test.txt).
        finder = DAOStarFinder(
            fwhm=float(fwhm_px), threshold=threshold,
            sharplo=DAO_SHARPLO, sharphi=DAO_SHARPHI,
            roundlo=DAO_ROUNDLO, roundhi=DAO_ROUNDHI,
            exclude_border=True,
        )
    sources = finder(image)
    if sources is None or len(sources) == 0:
        return np.zeros((0, 3), dtype=np.float64)
    x_col, y_col = _dao_column(sources, "xcentroid"), _dao_column(sources, "ycentroid")
    if x_col is None or y_col is None:
        raise RuntimeError(f"DAOStarFinder sin columnas de centroide; columnas={getattr(sources, 'colnames', None)}")
    xs = np.asarray(sources[x_col], float)
    ys = np.asarray(sources[y_col], float)
    flux_col = _dao_column(sources, "flux")
    flux = np.asarray(sources[flux_col], float) if flux_col else np.ones_like(xs)
    good = np.isfinite(xs) & np.isfinite(ys) & np.isfinite(flux)
    xs, ys, flux = xs[good], ys[good], flux[good]
    order = np.argsort(flux)[::-1][: int(max_sources)]
    xs, ys, flux = xs[order], ys[order], flux[order]
    logger.info("DAOStarFinder: %d fuentes (sigma=%.1f, fwhm=%.1f px)", len(xs), threshold_sigma, fwhm_px)
    return np.column_stack([xs, ys, flux]).astype(np.float64)


def _find_point_sources_fallback(
    data: np.ndarray, background: Background, *, fwhm_px: float, threshold_sigma: float, max_sources: int,
    roundness_max: float = 0.55, min_fwhm_factor: float = 0.55, max_fwhm_factor: float = 2.0,
    edge_margin: int | None = None,
) -> np.ndarray:
    """Detección robusta en Python puro -- máximos locales de la imagen
    suavizada por gaussiana, filtrados por S/N local, elipticidad y FWHM
    de forma (momentos de segundo orden), con separación mínima entre
    picos. Reserva cuando `DAOStarFinder` falla en tiempo real (no
    "photutils ausente": es dependencia dura de este producto), p. ej.
    ante una incompatibilidad de columnas no cubierta por `_dao_column`.
    """
    sigma_px = max(float(fwhm_px) / _FWHM_TO_SIGMA, 0.4)
    image = np.asarray(data, np.float32) - np.asarray(background.bkg, np.float32)
    image = np.where(np.isfinite(image), image, 0.0)
    noise = np.maximum(np.asarray(background.rms, np.float32), 1e-6)
    smoothed = ndi.gaussian_filter(image, sigma_px)
    size = max(3, int(2 * math.ceil(fwhm_px) + 1))
    peaks = (smoothed == ndi.maximum_filter(smoothed, size=size, mode="nearest")) & (
        smoothed > float(threshold_sigma) * noise
    )
    ys, xs = np.nonzero(peaks)
    if xs.size == 0:
        return np.zeros((0, 3), dtype=np.float64)

    order = np.argsort(smoothed[ys, xs])[::-1][: max_sources * 6]
    radius = max(2, int(math.ceil(2.2 * fwhm_px)))
    height, width = image.shape
    margin = radius + 1 if edge_margin is None else int(edge_margin)
    min_separation = max(1.0, 0.55 * fwhm_px)
    out: list[tuple[float, float, float]] = []

    for k in order:
        x0, y0 = int(xs[k]), int(ys[k])
        if x0 < margin or y0 < margin or x0 >= width - margin or y0 >= height - margin:
            continue
        cut = image[y0 - radius : y0 + radius + 1, x0 - radius : x0 + radius + 1]
        if cut.size == 0:
            continue
        finite_cut = np.isfinite(cut)
        if finite_cut.sum() < 0.6 * cut.size:
            continue
        peak = float(image[y0, x0])
        if not math.isfinite(peak) or peak <= 0:
            continue
        weights = np.clip(np.where(finite_cut, cut, 0.0), 0.0, None)
        total = float(weights.sum())
        if total <= 0:
            continue
        local_noise = float(
            np.median(noise[y0 - radius : y0 + radius + 1, x0 - radius : x0 + radius + 1])
        )
        local_noise = max(local_noise, 1e-6)
        if peak / local_noise < threshold_sigma:
            continue
        grid_y, grid_x = np.mgrid[-radius : radius + 1, -radius : radius + 1]
        cx = float((weights * grid_x).sum() / total)
        cy = float((weights * grid_y).sum() / total)
        mxx = float((weights * (grid_x - cx) ** 2).sum() / total)
        myy = float((weights * (grid_y - cy) ** 2).sum() / total)
        mxy = float((weights * (grid_x - cx) * (grid_y - cy)).sum() / total)
        trace = mxx + myy
        det = max(mxx * myy - mxy * mxy, 0.0)
        if trace <= 0:
            continue
        disc = math.sqrt(max(0.25 * trace * trace - det, 0.0))
        l1 = trace / 2 + disc
        l2 = max(trace / 2 - disc, 1e-9)
        ellipticity = 1.0 - math.sqrt(l2 / l1)
        if ellipticity > roundness_max:
            continue
        fwhm_major = _FWHM_TO_SIGMA * math.sqrt(l1)
        fwhm_minor = _FWHM_TO_SIGMA * math.sqrt(l2)
        if not (min_fwhm_factor * fwhm_px <= fwhm_minor <= max_fwhm_factor * fwhm_px):
            continue
        if not (min_fwhm_factor * fwhm_px <= fwhm_major <= max_fwhm_factor * fwhm_px):
            continue
        x, y = x0 + cx, y0 + cy
        if any(math.hypot(x - px, y - py) < min_separation for px, py, _ in out):
            continue
        out.append((x, y, total))
        if len(out) >= max_sources:
            break
    return np.asarray(out, dtype=np.float64).reshape(-1, 3)


def find_point_sources(
    data: np.ndarray, background: Background, *, fwhm_px: float = 3.0, threshold_sigma: float = 5.0,
    max_sources: int = 3000,
) -> np.ndarray:
    """Detecta fuentes puntuales -> array `(N, 3)` de `[x_px, y_px, flux]`,
    ordenado de más a menos brillante. `DAOStarFinder` es el algoritmo
    real; si falla en tiempo de ejecución sobre estos datos concretos
    (no por ausencia del paquete: es dependencia dura), se usa la
    reserva en Python puro -- nunca una lista vacía por una excepción no
    capturada."""
    try:
        return _find_point_sources_dao(
            data, background, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
        )
    except Exception as exc:
        logger.warning("DAOStarFinder no utilizable (%s); usando detector robusto de reserva", exc)
        return _find_point_sources_fallback(
            data, background, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_sources
        )


@dataclass(frozen=True)
class EnrichedSource:
    """Métricas locales auditables de una fuente puntual, vía momentos
    de segundo orden -- independientes de cualquier catálogo externo."""

    det_id: int
    x_px: float
    y_px: float
    flux_adu: float
    peak_adu: float
    snr_peak: float
    local_rms_adu: float
    local_snr_median: float
    roi_mean_adu: float
    roi_median_adu: float
    fwhm_px: float
    ellipticity: float
    """0 = circular, -> 1 = muy alargada."""
    sharpness_index: float
    border_distance_px: float
    saturated: bool
    quality: str
    """`"ok"` | `"saturated"` | `"edge"` | `"low_snr"`."""


def enrich_detections(
    data: np.ndarray, background: Background, sources: np.ndarray, *, saturate_adu: float | None = None,
) -> list[EnrichedSource]:
    """Enriquece cada fuente cruda `(x, y[, flux])` con sus métricas
    locales reales.

    `saturate_adu`, si se da, es el valor real de saturación del sensor
    (típicamente `header["SATURATE"]`) -- sin él, la detección de
    saturación queda inactiva en vez de inventar un umbral (p. ej. sobre
    un array en memoria sin cabecera FITS real detrás)."""
    if sources is None:
        return []
    source_array = np.atleast_2d(np.asarray(sources, float))
    if source_array.size == 0:
        return []
    if source_array.shape[1] < 2:
        raise ValueError("enrich_detections: sources debe contener x,y[,flux]")

    image = np.asarray(data, np.float32) - np.asarray(background.bkg, np.float32)
    rms = np.maximum(np.asarray(background.rms, np.float32), 1e-12)
    if image.ndim != 2 or rms.shape != image.shape:
        raise ValueError("enrich_detections: imagen y mapa RMS deben ser 2D y de igual forma")
    height, width = image.shape

    rows: list[EnrichedSource] = []
    for det_id, row in enumerate(source_array, 1):
        x, y = float(row[0]), float(row[1])
        flux = float(row[2]) if row.size >= 3 and math.isfinite(row[2]) else float("nan")
        xi, yi = int(round(x)), int(round(y))
        radius = 11
        y0, y1 = max(0, yi - radius), min(height, yi + radius + 1)
        x0, x1 = max(0, xi - radius), min(width, xi + radius + 1)
        cut = image[y0:y1, x0:x1]
        local_rms = rms[y0:y1, x0:x1]
        good = np.isfinite(cut) & np.isfinite(local_rms) & (local_rms > 0)

        peak = float(np.nanmax(cut)) if np.isfinite(cut).any() else float("nan")
        noise = float(np.nanmedian(local_rms[good])) if np.any(good) else float("nan")
        local_snr_median = float(np.nanmedian(cut[good] / local_rms[good])) if np.any(good) else float("nan")
        roi_mean = float(np.nanmean(cut)) if np.isfinite(cut).any() else float("nan")
        roi_median = float(np.nanmedian(cut)) if np.isfinite(cut).any() else float("nan")
        snr_peak = peak / max(noise, 1e-12) if math.isfinite(peak) and math.isfinite(noise) else float("nan")
        border = float(min(x, width - 1 - x, y, height - 1 - y))

        weights = np.clip(np.nan_to_num(cut, nan=0.0), 0, None)
        grid_y, grid_x = np.mgrid[y0:y1, x0:x1]
        total = float(weights.sum())
        fwhm = ellipticity = sharpness = float("nan")
        if total > 0:
            cx = float((weights * grid_x).sum() / total)
            cy = float((weights * grid_y).sum() / total)
            mxx = float((weights * (grid_x - cx) ** 2).sum() / total)
            myy = float((weights * (grid_y - cy) ** 2).sum() / total)
            mxy = float((weights * (grid_x - cx) * (grid_y - cy)).sum() / total)
            trace = mxx + myy
            disc = math.sqrt(max(0.25 * (mxx - myy) ** 2 + mxy * mxy, 0.0))
            l1 = max(trace / 2 + disc, 1e-9)
            l2 = max(trace / 2 - disc, 1e-9)
            # FWHM de la media geométrica de sigma_major/sigma_minor:
            # sigma_i = sqrt(l_i), fwhm_i = 2.3548*sigma_i, media
            # geométrica = 2.3548*(l1*l2)**0.25. La versión legacy
            # calculaba `2.3548*sqrt(l1*l2)` -- SIN la segunda raíz --
            # que no son las mismas unidades: `l1*l2` está en px^4
            # (varianza al cuadrado), no en px^2, así que ese resultado
            # nunca fue un FWHM real. Verificado con una gaussiana
            # sintética de sigma conocido (docs/audit/54-CIERRE-DETECTION.md):
            # con sigma=3px (FWHM real=7.06px) la fórmula legacy medía
            # 21.15px -- 3 veces demasiado grande, y la inflación CRECE
            # con el propio FWHM real (no es un offset fijo). El propio
            # detector de reserva (`_find_point_sources_fallback`, más
            # arriba en este archivo) ya usaba la fórmula correcta
            # (`2.3548*sqrt(l1)` y `2.3548*sqrt(l2)` por separado) para
            # su propio filtro de forma: el error estaba solo aquí, en
            # el enriquecimiento que se reporta después.
            fwhm = _FWHM_TO_SIGMA * math.sqrt(math.sqrt(l1 * l2))
            ellipticity = 1.0 - math.sqrt(l2 / l1)
            rr2 = (grid_x - cx) ** 2 + (grid_y - cy) ** 2
            r_core = max(1.5, fwhm / 2)
            r_annulus = max(2.5, fwhm)
            core = float(weights[rr2 <= r_core**2].sum())
            annulus = float(weights[(rr2 > r_core**2) & (rr2 <= r_annulus**2)].sum())
            sharpness = core / max(annulus, 1e-12)

        saturated = bool(
            saturate_adu is not None and math.isfinite(saturate_adu) and math.isfinite(peak)
            and peak >= 0.999 * saturate_adu
        )
        edge_threshold = max(5.0, fwhm if math.isfinite(fwhm) else 5.0)
        quality = (
            "saturated" if saturated
            else "edge" if border < edge_threshold
            else "ok" if math.isfinite(snr_peak) and snr_peak >= 5
            else "low_snr"
        )
        rows.append(
            EnrichedSource(
                det_id=det_id, x_px=x, y_px=y, flux_adu=flux, peak_adu=peak, snr_peak=snr_peak,
                local_rms_adu=noise, local_snr_median=local_snr_median, roi_mean_adu=roi_mean,
                roi_median_adu=roi_median, fwhm_px=float(fwhm), ellipticity=float(ellipticity),
                sharpness_index=float(sharpness), border_distance_px=border, saturated=saturated,
                quality=quality,
            )
        )
    return rows
