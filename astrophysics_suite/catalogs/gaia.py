"""Identificación contra Gaia DR3 -> `IdentificationState` + `CatalogMatch`/
`CatalogQuery`.
"""
from __future__ import annotations

import math
import threading

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import crossmatch_gaia_safe as _legacy_crossmatch_gaia_safe

from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg
from astrophysics_suite.core.enums import IdentificationState, ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import CatalogMatch, CatalogQuery
from astrophysics_suite.models.detection import Detection

CATALOG_NAME = "Gaia DR3"

# Estado real (aislado por hilo -- cada `DiscoveryJob` corre en su propio
# hilo de fondo, ver `services/discovery_service.py`) de la última llamada
# real a `query_gaia_neighbors` en ESTE hilo. Antes de cualquier llamada
# real, o cuando `query_gaia_neighbors` ha sido sustituida por un doble de
# prueba (nunca ejecuta el cuerpo real, nunca toca este estado), se asume
# disponible -- la semántica correcta para un doble que simula "Gaia
# respondió, aquí están (o no) los resultados".
_gaia_availability_state = threading.local()


def _query_local_cache(
    ra_deg: float, dec_deg: float, *, radius_arcsec: float, mag_limit: float, max_rows: int,
) -> tuple[list[dict], bool]:
    """Consulta la caché local en disco. Nunca lanza: si la caché no
    existe, está corrupta o no se puede leer, se comporta exactamente
    como "este campo no está descargado" y la consulta sigue por red --
    un problema con la caché nunca debe impedir un análisis."""
    try:
        from astrophysics_suite.catalogs.local_cache import CatalogCache

        return CatalogCache("gaia").query_neighbors(
            ra_deg, dec_deg, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows,
        )
    except Exception:
        return [], False


def last_gaia_availability() -> tuple[bool, str]:
    """`(disponible, detalle)` de la última consulta real a Gaia en este
    hilo -- usado por `identify_detection` para no confundir "se consultó
    Gaia de verdad y no había ninguna fuente cerca" (UNMATCHED real) con
    "Gaia no respondió, nunca se pudo comprobar" (que debe degradar a
    DISCOVERY_REVIEW, nunca declararse como no-coincidencia confirmada)."""
    return getattr(_gaia_availability_state, "available", True), getattr(_gaia_availability_state, "detail", "")


def query_gaia_neighbors(
    ra_deg: float, dec_deg: float, *, radius_arcsec: float = 3.0, mag_limit: float = 20.0, max_rows: int = 25
) -> list[dict]:
    """Consulta Gaia DR3 alrededor de (ra_deg, dec_deg). Devuelve una lista
    de dicts (posiblemente vacía si Gaia no está disponible o falla la
    consulta -- nunca lanza; delega en el manejo de errores ya probado de
    `crossmatch_gaia_safe`, que captura toda excepción de red/servicio).

    También registra en `last_gaia_availability()` si esta consulta real
    pudo hablar con Gaia -- una lista vacía por sí sola no distingue "sin
    fuentes en el radio" de "el servicio no respondió", y esa distinción
    es la que necesita `identify_detection` para no declarar UNMATCHED
    sin haber consultado de verdad.

    **La caché local va primero**: si el campo ya se descargó a disco
    (ver `catalogs/local_cache.py`), se sirve desde ahí y no se toca la
    red -- así un análisis con 1320 detecciones hace 0 consultas en vez
    de 1320, y funciona sin internet. Solo si esa posición NO está
    cubierta por ninguna descarga previa se consulta el servicio real."""
    cached_rows, covered = _query_local_cache(ra_deg, dec_deg, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows)
    if covered:
        _gaia_availability_state.available = True
        _gaia_availability_state.detail = ""
        return cached_rows

    result = _legacy_crossmatch_gaia_safe(ra_deg, dec_deg, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows)
    available = result.get("state") == "OBSERVABLE" and bool(result.get("gaia_available"))
    _gaia_availability_state.available = available
    _gaia_availability_state.detail = "" if available else str(result.get("error") or result.get("state") or "motivo desconocido")
    if available:
        return result.get("sources", [])
    return []


def classify_against_gaia_neighbors(
    detection: Detection, gaia_rows: list[dict], *, match_radius_arcsec: float = 3.0, gaia_available: bool = True, gaia_unavailable_detail: str = "",
) -> tuple[IdentificationState, tuple[CatalogMatch, ...], tuple[CatalogQuery, ...]]:
    """Función pura: dado un Detection con coordenadas celestes y una lista
    ya obtenida de fuentes Gaia cercanas, decide el IdentificationState y
    construye los registros de match/no-match. No hace ninguna llamada de
    red -- por eso es la parte de este motor que se puede probar sin red.

    `gaia_available` distingue "se consultó Gaia de verdad y la lista
    viene vacía porque no hay fuentes en el radio" (UNMATCHED real) de
    "Gaia no respondió, nunca se pudo consultar" (DISCOVERY_REVIEW --
    ausencia de respuesta nunca se declara como ausencia de fuente,
    confirmado tras encontrarse candidatos reales de M 31 marcados
    UNMATCHED en un entorno sin red hacia Gaia)."""
    if not detection.position.has_sky_coordinates:
        return (
            IdentificationState.DISCOVERY_REVIEW,
            (),
            (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason="sin coordenadas celestes (sin WCS válido)"),),
        )

    if not gaia_rows:
        if not gaia_available:
            detail = f": {gaia_unavailable_detail}" if gaia_unavailable_detail else ""
            return (
                IdentificationState.DISCOVERY_REVIEW,
                (),
                (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason=f"Gaia no disponible, no se pudo comprobar si hay una fuente catalogada cerca{detail}"),),
            )
        return (
            IdentificationState.UNMATCHED,
            (),
            (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason="sin fuentes Gaia en el radio de búsqueda"),),
        )

    def separation(row: dict) -> float:
        # `angular_separation_deg` (astrometry/wcs_fit.py) es la misma
        # fórmula de gran círculo que ya usaba `legacy.angular_separation_
        # arcsec` (verificado numéricamente: diferencia < 1e-10" sobre
        # 20000 pares aleatorios) -- una sola implementación real en vez
        # de dos que puedan divergir, mismo criterio que el resto del
        # proyecto (p. ej. `pixel_scale_arcsec_per_px` en `instruments/optics.py`).
        return angular_separation_deg(detection.position.ra_deg, detection.position.dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0

    best = min(gaia_rows, key=separation)
    best_sep = separation(best)

    if best_sep > match_radius_arcsec:
        return (
            IdentificationState.UNMATCHED,
            (),
            (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason=f"fuente Gaia más cercana a {best_sep:.2f}\", fuera del radio de match"),),
        )

    mag = best.get("mag_g")
    match = CatalogMatch(
        catalog=CATALOG_NAME,
        catalog_id=str(best.get("source_id", "")),
        separation_arcsec=best_sep,
        magnitude=Quantity(value=float(mag), error=None, unit="mag", kind=ValueKind.OBSERVED, method="gaia_phot_g_mean_mag") if mag is not None and math.isfinite(float(mag)) else None,
    )
    return IdentificationState.KNOWN, (match,), ()


def identify_detection(
    detection: Detection, *, match_radius_arcsec: float = 3.0, mag_limit: float = 20.0, max_rows: int = 25
) -> tuple[IdentificationState, tuple[CatalogMatch, ...], tuple[CatalogQuery, ...]]:
    """Orquesta consulta real + clasificación pura."""
    if not detection.position.has_sky_coordinates:
        return classify_against_gaia_neighbors(detection, [], match_radius_arcsec=match_radius_arcsec)
    # Se reinicia al valor por defecto ANTES de consultar: el estado de
    # `last_gaia_availability()` es por hilo, no por llamada -- sin este
    # reinicio, una llamada real anterior en el mismo hilo (p. ej. otra
    # detección de la misma tanda, o incluso otra prueba en el mismo
    # proceso de pytest) podría dejar `available=False` puesto y
    # contaminar esta llamada aunque `query_gaia_neighbors` esté
    # sustituida por un doble que nunca toca ese estado.
    _gaia_availability_state.available = True
    _gaia_availability_state.detail = ""
    gaia_rows = query_gaia_neighbors(
        detection.position.ra_deg, detection.position.dec_deg, radius_arcsec=match_radius_arcsec, mag_limit=mag_limit, max_rows=max_rows
    )
    gaia_available, gaia_detail = last_gaia_availability()
    return classify_against_gaia_neighbors(
        detection, gaia_rows, match_radius_arcsec=match_radius_arcsec, gaia_available=gaia_available, gaia_unavailable_detail=gaia_detail,
    )
