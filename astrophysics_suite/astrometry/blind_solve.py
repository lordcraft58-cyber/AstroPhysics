"""Resolución de placa CIEGA -- sin RA/Dec aproximado en el header, sin
nombre de objeto resoluble por SIMBAD. `plate_solve.solve_plate` (ver su
docstring) SIEMPRE necesita un puntero aproximado; esto elimina esa
condición reutilizando el mismo principio que astrometry.net, ASTAP o el
"blind solving" de PixInsight: **hashing geométrico de asterismos**.

## La idea, en una frase

La FORMA de un grupo de 4 estrellas (sus posiciones relativas, no sus
coordenadas absolutas) es la misma vista desde cualquier orientación,
escala o traslación -- rotar/encoger/desplazar la imagen entera no
cambia qué asterismos hay en ella, solo dónde caen. Codificando esa
forma en 4 números invariantes, un asterismo detectado en la imagen se
puede buscar directamente en un índice de asterismos del catálogo de
referencia sin saber antes dónde apunta la imagen -- es la posición del
match lo que revela el puntero, no al revés.

## Cómo se construye el código (el mismo principio que astrometry.net)

Para 4 puntos: se toma el par MÁS SEPARADO (A, B) como referencia --
define una transformación de similitud (rotación + escala + traslación)
que lleva A al origen y B a (1, 0). Los otros dos puntos, expresados en
ese marco local, dan 4 números (Cx, Cy, Dx, Dy) que ya no dependen de la
orientación/escala/posición original del grupo -- solo de su forma. El
orden C/D se fija por convención (Cx <= Dx) para que el mismo grupo
físico produzca siempre el mismo código sin importar en qué orden
llegaron los puntos.

## Por qué esto NO es "inventar" una solución sin datos

El código sigue necesitando un catálogo de referencia real contra el que
buscar -- normalmente la caché local ya descargada (`catalogs/
local_cache.py`, poblada por una resolución de placa previa o una
descarga explícita del usuario). Sin ningún catálogo local, esto lo dice
explícitamente y no intenta nada -- nunca golpea Gaia a ciegas sobre
"todo el cielo" (miles de consultas, sin límite razonable de tiempo).

Cada coincidencia de asterismo es solo una PROPUESTA: se usa para
estimar un puntero/escala semilla (con `fit_wcs`, ya probado) y esa
semilla se entrega íntegra a `plate_solve.solve_plate`, que hace la
verificación real (rejilla de rotación, ajuste robusto, RMS máximo,
mínimo de estrellas emparejadas) -- el mismo criterio que ya protege la
resolución no ciega. Un asterismo falso casi nunca sobrevive esa
segunda pasada."""
from __future__ import annotations

import itertools
import math
import time
from dataclasses import dataclass, replace

import numpy as np
from scipy.spatial import cKDTree

from astrophysics_suite.astrometry.plate_solve import PlateSolveResult, solve_plate
from astrophysics_suite.astrometry.wcs_fit import fit_wcs, gnomonic_project
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.detection.point_sources import detect_point_sources_in_array

PROVIDER_NAME = "local (hashing geométrico de asterismos contra catálogo local, sin puntero previo)"
ENGINE_NAME = "astrometry.blind_solve"
ENGINE_VERSION = "1.0"

#: Vecinos más cercanos usados para formar el asterismo de cada estrella
#: -- 3 vecinos + la propia estrella = grupos de 4, el mínimo real que
#: hace falta para un código invariante. Más vecinos darían asterismos
#: más robustos frente a estrellas espurias pero también más caros de
#: indexar; 3 es lo mismo que usa astrometry.net en su variante más simple.
DEFAULT_K_NEIGHBORS = 3

DEFAULT_MAX_CATALOG_STARS = 500
DEFAULT_MAX_IMAGE_STARS = 40

#: Tolerancia del código (adimensional: el marco local normaliza AB a
#: longitud 1, así que esto es una fracción de esa longitud) -- cubre
#: ruido de centroide real sin generar tantos falsos positivos como para
#: que la verificación de `solve_plate` tenga que descartar demasiados.
DEFAULT_CODE_TOLERANCE = 0.02


@dataclass(frozen=True)
class Quad:
    """Un asterismo de 4 estrellas con su código invariante y las 4
    posiciones originales en el orden canónico (A, B, C, D) que produjo
    ese código -- así una coincidencia de código da directamente la
    correspondencia punto a punto, sin ambigüedad de orden."""

    code: tuple[float, float, float, float]
    positions: tuple[tuple[float, float], tuple[float, float], tuple[float, float], tuple[float, float]]


def _quad_code_and_order(points: np.ndarray) -> tuple[tuple[float, float, float, float], tuple[int, int, int, int]] | None:
    """Código invariante de 4 puntos (ver el docstring del módulo) + el
    orden de índices originales (A, B, C, D) que lo produjo. `None` si
    los 4 puntos son degenerados (coincidentes o colineales de forma que
    el par más separado tiene longitud ~0)."""
    if points.shape != (4, 2):
        return None
    best_pair, best_dist = None, -1.0
    for i, j in itertools.combinations(range(4), 2):
        dist = float(np.hypot(points[i, 0] - points[j, 0], points[i, 1] - points[j, 1]))
        if dist > best_dist:
            best_dist, best_pair = dist, (i, j)
    if best_pair is None or best_dist <= 1e-9:
        return None
    i, j = best_pair
    others = [k for k in range(4) if k not in (i, j)]

    def build(a_idx: int, b_idx: int):
        a, b = points[a_idx], points[b_idx]
        delta = b - a
        scale = float(np.hypot(delta[0], delta[1]))
        if scale <= 1e-12:
            return None
        cos_t, sin_t = delta[0] / scale, delta[1] / scale

        def to_local(p: np.ndarray) -> tuple[float, float]:
            v = p - a
            x = (v[0] * cos_t + v[1] * sin_t) / scale
            y = (-v[0] * sin_t + v[1] * cos_t) / scale
            return x, y

        c_local, d_local = to_local(points[others[0]]), to_local(points[others[1]])
        c_idx, d_idx = others[0], others[1]
        if c_local[0] > d_local[0]:
            c_local, d_local = d_local, c_local
            c_idx, d_idx = d_idx, c_idx
        return (c_local[0], c_local[1], d_local[0], d_local[1]), (a_idx, b_idx, c_idx, d_idx)

    candidates = [c for c in (build(i, j), build(j, i)) if c is not None]
    if not candidates:
        return None
    # Las dos asignaciones posibles de A/B dan códigos distintos en
    # general -- se elige la menor por orden lexicográfico como
    # convención determinista, así el mismo grupo físico da SIEMPRE el
    # mismo código sin importar en qué orden se pasaron los 4 puntos.
    return min(candidates, key=lambda item: item[0])


def _nearest_neighbor_groups(xy: np.ndarray, *, k_neighbors: int) -> list[list[int]]:
    """Un grupo por punto: el propio punto + sus `k_neighbors` vecinos
    más cercanos (mismo criterio en la imagen y en el catálogo, así el
    mismo asterismo físico se forma en ambos lados)."""
    n = len(xy)
    if n < k_neighbors + 1:
        return []
    tree = cKDTree(xy)
    _, indices = tree.query(xy, k=k_neighbors + 1)
    return [list(row) for row in indices]


def build_reference_quads(
    catalog_rows: list[dict], *, k_neighbors: int = DEFAULT_K_NEIGHBORS, max_stars: int = DEFAULT_MAX_CATALOG_STARS,
) -> list[Quad]:
    """Índice de asterismos del catálogo de referencia. Cada fila debe
    traer `ra_deg`/`dec_deg` reales (y opcionalmente `mag_g`, usada solo
    para priorizar cuáles de `catalog_rows` se conservan si hay más de
    `max_stars`, nunca para descartar sin motivo). Sin al menos
    `k_neighbors + 1` fuentes utilizables, no hay ningún asterismo que
    formar y se devuelve una lista vacía -- no un error, es una situación
    real y legítima con una caché local pequeña."""
    usable = [row for row in catalog_rows if math.isfinite(row.get("ra_deg", float("nan"))) and math.isfinite(row.get("dec_deg", float("nan")))]
    if len(usable) > max_stars:
        usable = sorted(usable, key=lambda row: row["mag_g"] if row.get("mag_g") is not None else 99.0)[:max_stars]
    if len(usable) < k_neighbors + 1:
        return []

    ra = np.array([row["ra_deg"] for row in usable], dtype=np.float64)
    dec = np.array([row["dec_deg"] for row in usable], dtype=np.float64)
    # Vecindad real por separación angular sobre la esfera, no por resta
    # ingenua de RA/Dec (falla cerca del polo o cruzando RA=0/360).
    mean_dec = float(np.mean(dec))
    xi = (ra - float(np.mean(ra))) * math.cos(math.radians(mean_dec))
    eta = dec - float(np.mean(dec))
    groups = _nearest_neighbor_groups(np.column_stack([xi, eta]), k_neighbors=k_neighbors)

    quads: list[Quad] = []
    for group in groups:
        center_ra, center_dec = ra[group[0]], dec[group[0]]
        # Proyección tangencial LOCAL centrada en la propia estrella del
        # grupo -- el grupo abarca solo sus vecinos más próximos (un
        # campo pequeño), así que la aproximación de plano tangente no
        # introduce distorsión apreciable para un código que de todas
        # formas solo alimenta una PROPUESTA, verificada después.
        group_xi, group_eta = gnomonic_project(ra[group], dec[group], center_ra, center_dec)
        points = np.column_stack([group_xi, group_eta])[:4]
        result = _quad_code_and_order(points)
        if result is None:
            continue
        code, order = result
        sky_positions = tuple((float(ra[group[idx]]), float(dec[group[idx]])) for idx in order)
        quads.append(Quad(code=code, positions=sky_positions))
    return quads


def build_image_quads(
    detected_xy: np.ndarray, *, k_neighbors: int = DEFAULT_K_NEIGHBORS, max_stars: int = DEFAULT_MAX_IMAGE_STARS,
) -> list[Quad]:
    """Índice de asterismos detectados en la imagen -- mismo principio
    que `build_reference_quads`, pero directamente sobre posiciones de
    píxel (ya euclídeas, sin necesidad de proyección). `detected_xy` debe
    venir ordenado de más a menos brillante (como lo hace
    `detect_point_sources_in_array`) -- así `max_stars` conserva las
    fuentes más fiables, no una muestra arbitraria."""
    xy = np.asarray(detected_xy, dtype=np.float64)[:max_stars]
    groups = _nearest_neighbor_groups(xy, k_neighbors=k_neighbors)
    quads: list[Quad] = []
    for group in groups:
        points = xy[group][:4]
        result = _quad_code_and_order(points)
        if result is None:
            continue
        code, order = result
        pixel_positions = tuple((float(xy[group[idx], 0]), float(xy[group[idx], 1])) for idx in order)
        quads.append(Quad(code=code, positions=pixel_positions))
    return quads


@dataclass(frozen=True)
class _Candidate:
    code_distance: float
    pixel_xy: tuple[tuple[float, float], ...]
    sky_radec: tuple[tuple[float, float], ...]


def _rank_candidates(image_quads: list[Quad], reference_quads: list[Quad], *, tolerance: float) -> list[_Candidate]:
    if not image_quads or not reference_quads:
        return []
    reference_codes = np.array([q.code for q in reference_quads], dtype=np.float64)
    tree = cKDTree(reference_codes)
    image_codes = np.array([q.code for q in image_quads], dtype=np.float64)
    distances, indices = tree.query(image_codes, k=1)

    candidates = [
        _Candidate(code_distance=float(dist), pixel_xy=image_quads[i].positions, sky_radec=reference_quads[int(idx)].positions)
        for i, (dist, idx) in enumerate(zip(distances, indices))
        if dist <= tolerance
    ]
    candidates.sort(key=lambda c: c.code_distance)
    return candidates


def _seed_pointing_from_quad(pixel_xy: tuple[tuple[float, float], ...], sky_radec: tuple[tuple[float, float], ...], crpix_px: tuple[float, float]) -> tuple[float, float, float] | None:
    """Puntero/escala semilla a partir de UN asterismo de 4 estrellas
    (`fit_wcs`, ya probado en el resto del proyecto) -- solo una
    propuesta inicial; `solve_plate` es quien de verdad valida o
    descarta cada semilla con todas las estrellas detectadas, no solo 4."""
    try:
        solution = fit_wcs(list(pixel_xy), list(sky_radec), crpix_px=crpix_px)
    except (ValueError, np.linalg.LinAlgError):
        return None
    ra0, dec0 = solution.crval_deg
    scale_deg_per_px = float(np.sqrt(np.abs(np.linalg.det(solution.cd_matrix_deg_per_px))))
    scale_arcsec_px = scale_deg_per_px * 3600.0
    if not (math.isfinite(ra0) and math.isfinite(dec0) and math.isfinite(scale_arcsec_px) and scale_arcsec_px > 0):
        return None
    return ra0, dec0, scale_arcsec_px


def solve_plate_blind(
    data: np.ndarray,
    header: dict,
    *,
    catalog_rows: list[dict],
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_image_stars: int = DEFAULT_MAX_IMAGE_STARS,
    max_catalog_stars: int = DEFAULT_MAX_CATALOG_STARS,
    k_neighbors: int = DEFAULT_K_NEIGHBORS,
    code_tolerance: float = DEFAULT_CODE_TOLERANCE,
    max_candidates_tried: int = 25,
    seed_pointing_uncertainty_arcsec: float = 300.0,
    timeout_s: float = 60.0,
    pipeline_version: str = "",
    **solve_plate_kwargs,
) -> PlateSolveResult:
    """Resuelve el WCS de `data` SIN ningún puntero aproximado -- envoltorio
    delgado sobre `_solve_plate_blind_core` (mismos parámetros y
    comportamiento, ver su docstring) que adjunta al resultado FINAL la
    procedencia del motor CIEGO (`ENGINE_NAME` de este módulo) -- distinta
    de la que cada intento interno de verificación lleva ya por su cuenta
    vía `plate_solve.solve_plate`, que también recibe `pipeline_version`."""
    result = _solve_plate_blind_core(
        data, header, catalog_rows=catalog_rows, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma,
        max_image_stars=max_image_stars, max_catalog_stars=max_catalog_stars, k_neighbors=k_neighbors,
        code_tolerance=code_tolerance, max_candidates_tried=max_candidates_tried,
        seed_pointing_uncertainty_arcsec=seed_pointing_uncertainty_arcsec, timeout_s=timeout_s,
        pipeline_version=pipeline_version, **solve_plate_kwargs,
    )
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    return replace(result, provenance=provenance)


def _solve_plate_blind_core(
    data: np.ndarray,
    header: dict,
    *,
    catalog_rows: list[dict],
    fwhm_px: float = 3.0,
    threshold_sigma: float = 5.0,
    max_image_stars: int = DEFAULT_MAX_IMAGE_STARS,
    max_catalog_stars: int = DEFAULT_MAX_CATALOG_STARS,
    k_neighbors: int = DEFAULT_K_NEIGHBORS,
    code_tolerance: float = DEFAULT_CODE_TOLERANCE,
    max_candidates_tried: int = 25,
    seed_pointing_uncertainty_arcsec: float = 300.0,
    timeout_s: float = 60.0,
    pipeline_version: str = "",
    **solve_plate_kwargs,
) -> PlateSolveResult:
    """Resuelve el WCS de `data` SIN ningún puntero aproximado -- ni del
    header ni de un nombre de objeto -- emparejando asterismos reales
    contra `catalog_rows` (típicamente `CatalogCache(...).all_rows()`,
    ver `catalogs/local_cache.py`). Sin catálogo utilizable, falla
    explícitamente (nunca intenta "adivinar" una posición).

    Cada candidato de asterismo se prueba, de más a menos parecido, hasta
    encontrar uno que `plate_solve.solve_plate` valide de verdad (rejilla
    de rotación completa, ajuste robusto, RMS máximo) o hasta agotar
    `max_candidates_tried`/`timeout_s` -- se devuelve entonces el
    resultado (positivo o negativo) del ÚLTIMO candidato probado, con el
    número de candidatos intentados añadido al motivo."""
    start_time = time.monotonic()
    height, width = data.shape
    crpix_px = (width / 2.0, height / 2.0)

    if not catalog_rows:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=0, n_catalog_stars=0, n_matched=0,
            reason="sin catálogo de referencia local disponible: no se ha descargado ningún campo a la caché local "
                   "(Catálogos -> Descargar campo actual...) con el que formar asterismos -- el resolutor ciego "
                   "necesita ALGÚN catálogo de referencia, igual que cualquier otro programa de resolución de placa",
        )

    detected = detect_point_sources_in_array(data, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=max_image_stars)
    if len(detected) < k_neighbors + 1:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(catalog_rows), n_matched=0,
            reason=f"número insuficiente de estrellas detectadas ({len(detected)}) para formar un asterismo "
                   f"(hacen falta al menos {k_neighbors + 1})",
        )
    detected_xy = np.array([(x, y) for x, y, _flux in detected], dtype=np.float64)

    image_quads = build_image_quads(detected_xy, k_neighbors=k_neighbors, max_stars=max_image_stars)
    reference_quads = build_reference_quads(catalog_rows, k_neighbors=k_neighbors, max_stars=max_catalog_stars)
    if not image_quads or not reference_quads:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(catalog_rows), n_matched=0,
            reason="no se pudo construir ningún asterismo (imagen o catálogo con muy pocas fuentes utilizables)",
        )

    candidates = _rank_candidates(image_quads, reference_quads, tolerance=code_tolerance)
    if not candidates:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(catalog_rows), n_matched=0,
            reason=f"ningún asterismo detectado coincide con el catálogo de referencia dentro de la tolerancia "
                   f"({len(image_quads)} asterismo(s) de imagen frente a {len(reference_quads)} de catálogo) -- "
                   f"el campo puede no estar cubierto por la caché local, o hay muy pocas estrellas reales en común",
        )

    last_result: PlateSolveResult | None = None
    n_tried = 0
    for candidate in candidates[:max_candidates_tried]:
        if time.monotonic() - start_time > timeout_s:
            break
        seed = _seed_pointing_from_quad(candidate.pixel_xy, candidate.sky_radec, crpix_px)
        if seed is None:
            continue
        ra0, dec0, scale_guess = seed
        n_tried += 1
        last_result = solve_plate(
            data, header,
            approx_ra_deg=ra0, approx_dec_deg=dec0, approx_scale_arcsec_px=scale_guess,
            fwhm_px=fwhm_px, threshold_sigma=threshold_sigma,
            pointing_uncertainty_arcsec=seed_pointing_uncertainty_arcsec,
            timeout_s=max(1.0, timeout_s - (time.monotonic() - start_time)),
            pipeline_version=pipeline_version,
            **solve_plate_kwargs,
        )
        if last_result.success:
            return PlateSolveResult(
                success=True, solution=last_result.solution, provider=PROVIDER_NAME,
                n_detected_stars=last_result.n_detected_stars, n_catalog_stars=last_result.n_catalog_stars,
                n_matched=last_result.n_matched,
                reason=f"resuelto en ciego tras probar {n_tried} asterismo(s) candidato(s): {last_result.reason}",
                rotation_deg=last_result.rotation_deg, mirrored=last_result.mirrored,
            )

    if last_result is None:
        return PlateSolveResult(
            success=False, solution=None, provider=PROVIDER_NAME, n_detected_stars=len(detected), n_catalog_stars=len(catalog_rows), n_matched=0,
            reason=f"{len(candidates)} asterismo(s) candidato(s) encontrados pero ninguno produjo una semilla de "
                   f"puntero/escala válida",
        )
    return PlateSolveResult(
        success=False, solution=None, provider=PROVIDER_NAME,
        n_detected_stars=last_result.n_detected_stars, n_catalog_stars=last_result.n_catalog_stars, n_matched=last_result.n_matched,
        reason=f"se probaron {n_tried} de {len(candidates)} asterismo(s) candidato(s), ninguno se verificó de "
               f"extremo a extremo (mejor intento: {last_result.reason})",
    )
