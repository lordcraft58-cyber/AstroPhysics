"""Resolución de coordenadas por NOMBRE de objeto vía SIMBAD -- el mismo
flujo que "Spectrophotometric Color Calibration" de PixInsight: el
usuario escribe el nombre real del objeto (p. ej. "M 31"), se consulta
SIMBAD, y esas coordenadas alimentan la resolución astrométrica
automática (`astrometry.plate_solve.solve_plate`) como puntero
aproximado -- sin depender de que el header FITS traiga RA/Dec en un
formato reconocible (con software de captura real, a menudo está
ausente o en una clave distinta de las que se comprueban).

Reutiliza el `resolve_object_center` ya existente en el código heredado
(mismo patrón de esta migración que `catalogs/gaia.py` con
`crossmatch_gaia_safe`): consulta SIMBAD con una tabla de alias
conservadora para objetos Messier/NGC habituales, y nunca lanza --
cualquier fallo de red/servicio/nombre no resuelto se traduce a `None`,
nunca a una coordenada inventada.
"""
from __future__ import annotations

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import resolve_object_center as _legacy_resolve_object_center

CATALOG_NAME = "SIMBAD"


def resolve_object_coordinates(name: str) -> tuple[float, float, str] | None:
    """Consulta SIMBAD por `name`. Devuelve `(ra_deg, dec_deg, fuente)`
    si se resolvió, o `None` si no (nombre vacío, sin conectividad,
    SIMBAD no reconoce el nombre) -- nunca inventa coordenadas."""
    if not str(name or "").strip():
        return None
    ra, dec, source = _legacy_resolve_object_center(name)
    if ra is None or dec is None:
        return None
    return float(ra), float(dec), str(source)
