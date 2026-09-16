"""Identificación contra Gaia DR3 -> `IdentificationState` + `CatalogMatch`/
`CatalogQuery`.
"""
from __future__ import annotations

import math

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import angular_separation_arcsec
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import crossmatch_gaia_safe as _legacy_crossmatch_gaia_safe

from astrophysics_suite.core.enums import IdentificationState, ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import CatalogMatch, CatalogQuery
from astrophysics_suite.models.detection import Detection

CATALOG_NAME = "Gaia DR3"


def query_gaia_neighbors(
    ra_deg: float, dec_deg: float, *, radius_arcsec: float = 3.0, mag_limit: float = 20.0, max_rows: int = 25
) -> list[dict]:
    """Consulta Gaia DR3 alrededor de (ra_deg, dec_deg). Devuelve una lista
    de dicts (posiblemente vacía si Gaia no está disponible o falla la
    consulta -- nunca lanza; delega en el manejo de errores ya probado de
    `crossmatch_gaia_safe`, que captura toda excepción de red/servicio)."""
    result = _legacy_crossmatch_gaia_safe(ra_deg, dec_deg, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows)
    if result.get("state") == "OBSERVABLE" and result.get("gaia_available"):
        return result.get("sources", [])
    return []


def classify_against_gaia_neighbors(
    detection: Detection, gaia_rows: list[dict], *, match_radius_arcsec: float = 3.0
) -> tuple[IdentificationState, tuple[CatalogMatch, ...], tuple[CatalogQuery, ...]]:
    """Función pura: dado un Detection con coordenadas celestes y una lista
    ya obtenida de fuentes Gaia cercanas, decide el IdentificationState y
    construye los registros de match/no-match. No hace ninguna llamada de
    red -- por eso es la parte de este motor que se puede probar sin red."""
    if not detection.position.has_sky_coordinates:
        return (
            IdentificationState.DISCOVERY_REVIEW,
            (),
            (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason="sin coordenadas celestes (sin WCS válido)"),),
        )

    if not gaia_rows:
        return (
            IdentificationState.UNMATCHED,
            (),
            (CatalogQuery(catalog=CATALOG_NAME, radius_arcsec=match_radius_arcsec, reason="sin fuentes Gaia en el radio de búsqueda"),),
        )

    def separation(row: dict) -> float:
        return angular_separation_arcsec(detection.position.ra_deg, detection.position.dec_deg, row["ra_deg"], row["dec_deg"])

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
    gaia_rows = query_gaia_neighbors(
        detection.position.ra_deg, detection.position.dec_deg, radius_arcsec=match_radius_arcsec, mag_limit=mag_limit, max_rows=max_rows
    )
    return classify_against_gaia_neighbors(detection, gaia_rows, match_radius_arcsec=match_radius_arcsec)
