"""Resolución astrométrica automática ("plate solving") -- API real,
propia, sin envolver un binario/servicio de terceros: dado un puntero
aproximado (RA/Dec + escala de píxel, del header FITS o proporcionado
por el llamador), detecta estrellas reales (`detect_point_sources_in_array`),
consulta Gaia alrededor de ese puntero, y encuentra la rotación/orientación
real por búsqueda en rejilla + emparejamiento por vecino más cercano,
refinando con `fit_wcs` (mínimos cuadrados real, ya existente).

Alcance deliberado, documentado explícitamente (ver
`docs/audit/27-PLATE-SOLVING-AUTOMATICO.md`): esta función en concreto
REQUIERE una posición aproximada y una escala aproximada -- del header
FITS (RA/DEC, FOCALLEN+XPIXSZ, PIXSCALE) o proporcionadas explícitamente
-- y resuelve la orientación exacta (rotación + posible espejo),
refinando con estrellas reales. Cuando no hay información aproximada
suficiente, se informa explícitamente en vez de inventar una solución --
ver `estimate_approx_pointing_from_header`/`estimate_approx_scale_from_header`
devolviendo `None`.

El resolutor CIEGO (sin ningún puntero previo, al estilo astrometry.net)
vive aparte, en `astrometry/blind_solve.py`: empareja asterismos por
hashing geométrico contra un catálogo de referencia (típicamente la
caché local ya descargada) para producir un puntero/escala semilla, y
delega la verificación final en `solve_plate` -- por eso esta función
sigue existiendo tal cual, como el paso de verificación común a ambos
caminos (con puntero y ciego), en vez de duplicar la rejilla de rotación
y el ajuste robusto en dos sitios.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass, replace

import numpy as np
from scipy.spatial import cKDTree

from astrophysics_suite.astrometry.wcs_fit import WCSSolution, fit_wcs, gnomonic_project
from astrophysics_suite.catalogs.gaia import query_gaia_neighbors
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.detection.point_sources import detect_point_sources_in_array

PROVIDER_NAME = "local (rejilla de rotación + emparejamiento Gaia, sin binario/servicio externo)"
ENGINE_NAME = "astrometry.plate_solve"
ENGINE_VERSION = "1.0"


def estimate_approx_pointing_from_header(header: dict) -> tuple[float, float] | None:
    """RA/Dec aproximadas (grados) desde el header FITS -- `RA`/`DEC` u
    `OBJCTRA`/`OBJCTDEC` (sexagesimal o decimal, formatos habituales de
    cámaras/monturas reales). Devuelve `None` si no hay ninguna -- nunca
    inventa un puntero."""
    from astropy.coordinates import Angle
    import astropy.units as u

    for ra_key, dec_key in (("OBJCTRA", "OBJCTDEC"), ("RA", "DEC")):
        ra_raw, dec_raw = header.get(ra_key), header.get(dec_key)
        if ra_raw is None or dec_raw is None:
            continue
        try:
            if isinstance(ra_raw, str) and (" " in ra_raw or ":" in ra_raw):
                ra_deg = Angle(ra_raw.replace(" ", ":"), unit=u.hourangle).degree
            else:
                ra_deg = float(ra_raw)
            if isinstance(dec_raw, str) and (" " in dec_raw or ":" in dec_raw):
                dec_deg = Angle(dec_raw.replace(" ", ":"), unit=u.deg).degree
            else:
                dec_deg = float(dec_raw)
        except (ValueError, TypeError):
            continue
        if math.isfinite(ra_deg) and math.isfinite(dec_deg) and -90.0 <= dec_deg <= 90.0:
            return float(ra_deg) % 360.0, float(dec_deg)
    return None


def estimate_approx_scale_from_header(header: dict) -> float | None:
    """Escala aproximada (arcsec/px) desde el header FITS -- primero
    `PIXSCALE`/`SECPIX` directos si están, si no `FOCALLEN` (mm) +
    `XPIXSZ` (µm) -- la fórmula estándar `206265 * pixel_um / (focal_mm * 1000)`.
    Devuelve `None` si no hay suficiente información -- nunca asume un
    valor por defecto."""
    for key in ("PIXSCALE", "SECPIX", "PLTSCALE"):
        value = header.get(key)
        if value is not None:
            try:
                value = float(value)
            except (ValueError, TypeError):
                continue
            if math.isfinite(value) and value > 0:
                return value

    focal_mm = header.get("FOCALLEN")
    pixel_um = header.get("XPIXSZ", header.get("PIXSIZE1"))
    if focal_mm is not None and pixel_um is not None:
        try:
            focal_mm, pixel_um = float(focal_mm), float(pixel_um)
        except (ValueError, TypeError):
            return None
        if math.isfinite(focal_mm) and focal_mm > 0 and math.isfinite(pixel_um) and pixel_um > 0:
            return 206265.0 * (pixel_um / 1000.0) / focal_mm
    return None


@dataclass(frozen=True)
class PlateSolveResult:
    success: bool
    solution: WCSSolution | None
    provider: str
    n_detected_stars: int
    n_catalog_stars: int
    n_matched: int
    reason: str
    """Motivo del fallo si `success=False`; resumen legible si `success=True`."""
    rotation_deg: float | None = None
    mirrored: bool | None = None
    provenance: Provenance | None = None
    """Procedencia real del intento -- qué motor (`ENGINE_NAME` de este
    módulo o de `blind_solve.py`), qué versión y con qué versión del
    pipeline, tanto si tuvo éxito como si no: un intento fallido también
    es procedencia real (qué se probó y no pudo). `None` solo si el
    resultado se construyó fuera de `solve_plate`/`solve_plate_blind`
    (no debería ocurrir en producción)."""


def _build_trial_cd(scale_deg_per_px: float, rotation_rad: float, parity: int) -> np.ndarray:
    cos_t, sin_t = math.cos(rotation_rad), math.sin(rotation_rad)
    rotation = np.array([[cos_t, -sin_t], [sin_t, cos_t]])
    return scale_deg_per_px * np.array([[parity, 0.0], [0.0, 1.0]]) @ rotation


def _project_catalog_aligned_to_detected(
    catalog_radec: np.ndarray, ra0: float, dec0: float, cd: np.ndarray, detected_xy: np.ndarray, bin_px: float
) -> np.ndarray:
    """Proyecta el catálogo a píxeles con la orientación de prueba `cd`, y
    estima la TRASLACIÓN por votación tipo Hough -- en vez de asumir que
    `(ra0, dec0)` cae exactamente en el centro de la imagen (el puntero
    aproximado puede estar desviado por arcominutos, mucho más que la
    tolerancia de emparejamiento) NI que el centroide de las estrellas
    detectadas se aproxima al centroide del catálogo proyectado.

    Esa segunda asunción (probada con datos reales, no solo supuesta) es
    falsa en cuanto la detección es incompleta o no representativa --
    p. ej. dos estrellas próximas que el detector fusiona en una sola
    fuente, o estrellas cerca del límite de detección -- algo normal en
    datos reales, no un caso raro. Alinear por CENTROIDE desplaza
    entonces el catálogo entero varios píxeles de más, lo que puede
    hacer que una orientación incorrecta puntúe más alto que la
    correcta en la rejilla (bug real encontrado con datos sintéticos:
    7 de 35 estrellas fusionadas en pares próximos bastaron para que la
    orientación verdadera puntuara peor que una espejada/rotada).

    En su lugar: para cada pareja posible (estrella detectada, estrella
    de catálogo proyectada sin trasladar) se calcula la traslación que
    las haría coincidir, y se toma la traslación más votada (agrupando
    en una rejilla de tamaño `bin_px`). Las parejas correctas votan
    todas por (aproximadamente) la misma traslación; las incorrectas se
    reparten casi al azar por todo el rango posible -- robusto frente a
    una submuestra de detecciones no representativa, sin asumir nada
    sobre dónde cae el centro de la imagen."""
    xi, eta = gnomonic_project(catalog_radec[:, 0], catalog_radec[:, 1], ra0, dec0)
    raw_offset = np.linalg.solve(cd, np.vstack([xi, eta]))
    raw_xy = raw_offset.T
    if len(detected_xy) == 0 or len(raw_xy) == 0:
        return raw_xy

    diffs = (detected_xy[:, None, :] - raw_xy[None, :, :]).reshape(-1, 2)
    bins = np.round(diffs / bin_px).astype(np.int64)
    _, inverse, counts = np.unique(bins, axis=0, return_inverse=True, return_counts=True)
    best_bin_index = int(np.argmax(counts))
    best_translation = diffs[inverse.reshape(-1) == best_bin_index].mean(axis=0)
    return raw_xy + best_translation


_MAD_TO_SIGMA = 1.4826


def _robust_fit_wcs(
    pixel_xy: list[tuple[float, float]], sky_radec: list[tuple[float, float]], crpix_px: tuple[float, float],
    *, sigma_clip: float = 3.0, max_iterations: int = 3,
) -> WCSSolution:
    """`fit_wcs` real, con rechazo iterativo sigma-clip (MAD, el mismo
    criterio robusto usado en todo el proyecto -- estimación de cielo,
    combinación de fotogramas, punto cero fotométrico) de las parejas
    cuyo residuo se dispara. Una sola pareja mal emparejada entre varias
    correctas puede desviar bastante un ajuste por mínimos cuadrados
    ordinario -- el emparejamiento por vecino más cercano/mutuo no es
    perfecto, así que el propio ajuste debe poder descartar sus errores."""
    xy, radec = list(pixel_xy), list(sky_radec)
    solution = fit_wcs(xy, radec, crpix_px=crpix_px)
    for _ in range(max_iterations):
        if len(xy) < 4:
            break
        residuals = np.array(solution.residuals_arcsec)
        median = float(np.median(residuals))
        mad = float(np.median(np.abs(residuals - median)))
        sigma = max(mad * _MAD_TO_SIGMA, 1e-6)
        keep = np.abs(residuals - median) <= sigma_clip * sigma
        if bool(np.all(keep)) or int(np.sum(keep)) < 4:
            break
        xy = [p for p, k in zip(xy, keep) if k]
        radec = [s for s, k in zip(radec, keep) if k]
        solution = fit_wcs(xy, radec, crpix_px=crpix_px)
    return solution


def solve_plate(
    data: np.ndarray,
    header: dict,
    *,
    approx_ra_deg: float | None = None,
    approx_dec_deg: float | None = None,
    approx_scale_arcsec_px: float | None = None,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_stars: int = 40,
    match_radius_arcsec: float = 4.0,
    rotation_step_deg: float = 2.0,
    allow_flip: bool = True,
    min_matched_stars: int = 6,
    max_rms_arcsec: float = 2.0,
    gaia_mag_limit: float = 16.0,
    timeout_s: float = 30.0,
    pointing_uncertainty_arcsec: float = 600.0,
    pipeline_version: str = "",
) -> PlateSolveResult:
    """Resuelve el WCS de `data` de forma automática -- envoltorio
    delgado sobre `_solve_plate_core` (mismos parámetros y comportamiento,
    ver su docstring) que adjunta `PlateSolveResult.provenance` --
    `pipeline_version` con la que se produjo este intento concreto, tanto
    si tuvo éxito como si no."""
    result = _solve_plate_core(
        data, header,
        approx_ra_deg=approx_ra_deg, approx_dec_deg=approx_dec_deg, approx_scale_arcsec_px=approx_scale_arcsec_px,
        fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_stars=max_stars,
        match_radius_arcsec=match_radius_arcsec, rotation_step_deg=rotation_step_deg, allow_flip=allow_flip,
        min_matched_stars=min_matched_stars, max_rms_arcsec=max_rms_arcsec, gaia_mag_limit=gaia_mag_limit,
        timeout_s=timeout_s, pointing_uncertainty_arcsec=pointing_uncertainty_arcsec,
    )
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    return replace(result, provenance=provenance)


def _solve_plate_core(
    data: np.ndarray,
    header: dict,
    *,
    approx_ra_deg: float | None = None,
    approx_dec_deg: float | None = None,
    approx_scale_arcsec_px: float | None = None,
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_stars: int = 40,
    match_radius_arcsec: float = 4.0,
    rotation_step_deg: float = 2.0,
    allow_flip: bool = True,
    min_matched_stars: int = 6,
    max_rms_arcsec: float = 2.0,
    gaia_mag_limit: float = 16.0,
    timeout_s: float = 30.0,
    pointing_uncertainty_arcsec: float = 600.0,
) -> PlateSolveResult:
    """Resuelve el WCS de `data` de forma automática -- ver el docstring
    del módulo para el alcance real (requiere puntero aproximado, no es
    "blind solving" completo). `header` se usa solo para estimar el
    puntero/escala aproximados si no se proporcionan explícitamente --
    nunca para inventar un WCS directamente.

    `pointing_uncertainty_arcsec` acota cuánto puede desviarse el puntero
    aproximado del centro real de la placa (radio de búsqueda en Gaia =
    medio campo + este margen) -- 600" (10') es una estimación razonable
    para un GOTO de montura amateur; para un puntero muy fiable se puede
    bajar, para uno más incierto, subir."""
    start_time = time.monotonic()
    height, width = data.shape
    crpix_px = (width / 2.0, height / 2.0)

    ra0 = approx_ra_deg if approx_ra_deg is not None else None
    dec0 = approx_dec_deg if approx_dec_deg is not None else None
    if ra0 is None or dec0 is None:
        pointing = estimate_approx_pointing_from_header(header)
        if pointing is None:
            return PlateSolveResult(
                success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=0, n_catalog_stars=0, n_matched=0,
                reason="sin posición aproximada: no se proporcionó RA/Dec y el header no tiene RA/DEC ni OBJCTRA/OBJCTDEC -- "
                       "introduce un campo aproximado o ajusta el WCS manualmente",
            )
        ra0, dec0 = pointing

    scale = approx_scale_arcsec_px if approx_scale_arcsec_px is not None else estimate_approx_scale_from_header(header)
    if scale is None:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=0, n_catalog_stars=0, n_matched=0,
            reason="sin escala aproximada: no se proporcionó una escala y el header no tiene PIXSCALE/SECPIX ni "
                   "FOCALLEN+XPIXSZ -- introduce una escala aproximada (arcsec/px) o ajusta el WCS manualmente",
        )

    detected = detect_point_sources_in_array(data, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_stars)
    if len(detected) < min_matched_stars:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=0, n_matched=0,
            reason=f"número insuficiente de estrellas detectadas ({len(detected)}, se necesitan al menos {min_matched_stars}) -- "
                   f"baja el umbral de detección o comprueba que la imagen tenga suficiente señal",
        )
    detected_xy = np.array([(x, y) for x, y, _flux in detected], dtype=np.float64)

    field_diag_px = math.hypot(width, height)
    search_radius_arcsec = field_diag_px * scale * 0.5 + pointing_uncertainty_arcsec
    gaia_rows = query_gaia_neighbors(ra0, dec0, radius_arcsec=search_radius_arcsec, mag_limit=gaia_mag_limit, max_rows=300)
    if len(gaia_rows) < min_matched_stars:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=0,
            reason=f"Gaia no disponible o sin suficientes fuentes catalogadas cerca de RA={ra0:.4f} Dec={dec0:.4f} "
                   f"(radio {search_radius_arcsec:.0f}\"): {len(gaia_rows)} encontradas, se necesitan al menos {min_matched_stars}",
        )
    catalog_radec = np.array([(row["ra_deg"], row["dec_deg"]) for row in gaia_rows], dtype=np.float64)

    scale_deg = scale / 3600.0
    tolerance_px = match_radius_arcsec / scale
    # La rejilla de rotación (pasos de `rotation_step_deg`) y el primer
    # emparejamiento 1-a-1 usan una tolerancia más laxa que la validación
    # final: un paso de rejilla de, p. ej., 5° deja un error residual de
    # varios píxeles para una estrella lejos del centro incluso en la
    # orientación correcta -- `fit_wcs` es quien de verdad afina la
    # solución después, con una segunda pasada de emparejamiento ya con
    # la tolerancia estrecha (`tolerance_px`) sobre una solución precisa.
    search_tolerance_px = max(tolerance_px * 2.5, 3.0)
    detected_tree = cKDTree(detected_xy)

    best = None  # (score, rotation_rad, parity)
    second_best_score = 0
    parities = (1, -1) if allow_flip else (1,)
    rotation_steps = np.arange(0.0, 360.0, rotation_step_deg)
    for parity in parities:
        for rotation_deg_trial in rotation_steps:
            if time.monotonic() - start_time > timeout_s:
                return PlateSolveResult(
                    success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=0,
                    reason=f"tiempo de espera agotado ({timeout_s:.0f}s) buscando la orientación correcta -- prueba con una "
                           f"posición/escala aproximada más precisa o un rotation_step_deg mayor",
                )
            rotation_rad = math.radians(float(rotation_deg_trial))
            cd = _build_trial_cd(scale_deg, rotation_rad, parity)
            trial_xy = _project_catalog_aligned_to_detected(catalog_radec, ra0, dec0, cd, detected_xy, search_tolerance_px)

            distances, _ = detected_tree.query(trial_xy, k=1)
            score = int(np.sum(distances <= search_tolerance_px))
            if best is None or score > best[0]:
                second_best_score = best[0] if best is not None else 0
                best = (score, rotation_rad, parity)
            elif score > second_best_score:
                second_best_score = score

    best_score, best_rotation_rad, best_parity = best
    if best_score < min_matched_stars:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=best_score,
            reason=f"no se encontró ninguna orientación con suficientes correspondencias (mejor: {best_score}, se necesitan "
                   f"al menos {min_matched_stars}) -- la posición/escala aproximada puede ser incorrecta",
        )

    # Refinamiento: con la mejor orientación aproximada, emparejamiento
    # 1-a-1 real (vecino mutuo, no solo vecino más cercano de un lado) y
    # ajuste real por mínimos cuadrados (fit_wcs) -- la rejilla de arriba
    # solo elige la orientación, nunca decide la solución final.
    pixel_xy, sky_radec = _match_one_to_one(
        detected_xy, catalog_radec, ra0, dec0, scale_deg, best_rotation_rad, best_parity, search_tolerance_px
    )
    if len(pixel_xy) < min_matched_stars:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=len(pixel_xy),
            reason=f"el emparejamiento 1-a-1 dejó menos correspondencias de las necesarias ({len(pixel_xy)} < {min_matched_stars})",
        )

    solution = _robust_fit_wcs(pixel_xy, sky_radec, crpix_px)

    # Segunda pasada: con la solución ya ajustada (mucho más precisa que
    # la rejilla de 2° en 2°), se reproyecta el catálogo completo y se
    # reemparejan con tolerancia estrecha -- suele capturar más
    # correspondencias reales y afinar el RMS.
    refined_pixel_xy, refined_sky_radec = _match_one_to_one_with_solution(detected_xy, catalog_radec, solution, tolerance_px)
    if len(refined_pixel_xy) >= min_matched_stars:
        pixel_xy, sky_radec = refined_pixel_xy, refined_sky_radec
        solution = _robust_fit_wcs(pixel_xy, sky_radec, crpix_px)

    if solution.n_stars < min_matched_stars:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=solution.n_stars,
            reason=f"correspondencias insuficientes tras el ajuste final ({solution.n_stars} < {min_matched_stars})",
        )
    if solution.rms_residual_arcsec > max_rms_arcsec:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(gaia_rows), n_matched=solution.n_stars,
            reason=f"RMS del ajuste demasiado alto ({solution.rms_residual_arcsec:.2f}\" > {max_rms_arcsec:.2f}\") -- "
                   f"posible solución ambigua o puntero aproximado incorrecto",
        )

    ambiguous_note = ""
    if second_best_score > 0 and best_score < 1.3 * second_best_score:
        ambiguous_note = f" (aviso: la segunda mejor orientación tuvo {second_best_score} correspondencias, cerca de las {best_score} de la elegida -- revisa el resultado)"

    # Se reporta la rotación real extraída de la matriz CD ya ajustada
    # (precisa), no el valor de la rejilla que solo eligió la orientación
    # aproximada. `cd = scale * diag(parity, 1) @ R(theta)` -- la paridad
    # solo multiplica la fila 0 (`cd[0,0]`, `cd[0,1]`); la fila 1
    # (`cd[1,0]=scale*sin(theta)`, `cd[1,1]=scale*cos(theta)`) da theta
    # directamente, sin depender de la paridad (que sigue viniendo de la
    # búsqueda en rejilla, ya que `fit_wcs` no la busca por sí sola).
    final_cd = solution.cd_matrix_deg_per_px
    rotation_deg_final = math.degrees(math.atan2(final_cd[1, 0], final_cd[1, 1])) % 360.0

    return PlateSolveResult(
        success=True,
        solution=solution,
        provider=PROVIDER_NAME,
        n_detected_stars=len(detected),
        n_catalog_stars=len(gaia_rows),
        n_matched=solution.n_stars,
        reason=f"resuelto con {solution.n_stars} estrella(s), RMS={solution.rms_residual_arcsec:.2f}\"{ambiguous_note}",
        rotation_deg=rotation_deg_final,
        mirrored=best_parity < 0,
    )


def _match_one_to_one(
    detected_xy: np.ndarray,
    catalog_radec: np.ndarray,
    ra0: float,
    dec0: float,
    scale_deg: float,
    rotation_rad: float,
    parity: int,
    tolerance_px: float,
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    cd = _build_trial_cd(scale_deg, rotation_rad, parity)
    trial_xy = _project_catalog_aligned_to_detected(catalog_radec, ra0, dec0, cd, detected_xy, tolerance_px)
    return _mutual_nearest_neighbor_pairs(detected_xy, trial_xy, catalog_radec, tolerance_px)


def _match_one_to_one_with_solution(
    detected_xy: np.ndarray, catalog_radec: np.ndarray, solution: WCSSolution, tolerance_px: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    trial_xy = np.array([solution.sky_to_pixel(ra, dec) for ra, dec in catalog_radec])
    return _mutual_nearest_neighbor_pairs(detected_xy, trial_xy, catalog_radec, tolerance_px)


def _mutual_nearest_neighbor_pairs(
    detected_xy: np.ndarray, trial_xy: np.ndarray, catalog_radec: np.ndarray, tolerance_px: float
) -> tuple[list[tuple[float, float]], list[tuple[float, float]]]:
    """Emparejamiento 1-a-1 real: cada estrella detectada se empareja con
    la fuente de catálogo proyectada más cercana, y viceversa -- solo se
    aceptan las parejas donde ambas direcciones coinciden (vecino mutuo),
    dentro de la tolerancia. Evita que dos estrellas detectadas cercanas
    compitan por la misma fuente de catálogo de forma ambigua."""
    if len(trial_xy) == 0 or len(detected_xy) == 0:
        return [], []
    detected_tree = cKDTree(detected_xy)
    trial_tree = cKDTree(trial_xy)

    dist_det_to_trial, idx_det_to_trial = trial_tree.query(detected_xy, k=1)
    dist_trial_to_det, idx_trial_to_det = detected_tree.query(trial_xy, k=1)

    pixel_xy: list[tuple[float, float]] = []
    sky_radec: list[tuple[float, float]] = []
    for det_index, (dist, trial_index) in enumerate(zip(dist_det_to_trial, idx_det_to_trial)):
        if dist > tolerance_px:
            continue
        if idx_trial_to_det[trial_index] != det_index:
            continue  # no es vecino mutuo
        if dist_trial_to_det[trial_index] > tolerance_px:
            continue
        pixel_xy.append((float(detected_xy[det_index, 0]), float(detected_xy[det_index, 1])))
        sky_radec.append((float(catalog_radec[trial_index, 0]), float(catalog_radec[trial_index, 1])))
    return pixel_xy, sky_radec
