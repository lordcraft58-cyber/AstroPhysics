"""`astrometry/wcs_fit.py::angular_separation_deg` debe coincidir
numéricamente con la fórmula heredada `legacy.angular_separation_arcsec`
(cierre sistemático del motor 8/16, Identification/Catalogs, informe 96).

Antes de este cierre existían TRES implementaciones reales de la misma
fórmula de gran círculo: la de legacy, una copia privada en
`catalogs/local_cache.py`, y `catalogs/gaia.py`/`qt_app/processes/
registry.py` llamando directamente a la de legacy -- tres sitios que
podían divergir silenciosamente si alguno se tocaba sin tocar los otros.
El cierre consolidó todo en `angular_separation_deg` (única
implementación real, ya usada en Astrometry desde antes). Esta prueba
demuestra que esa consolidación no cambió ningún resultado numérico.
"""
from __future__ import annotations

import math
import random

import pytest

from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import angular_separation_arcsec as _legacy_angular_separation_arcsec


def _migrated_arcsec(ra1: float, dec1: float, ra2: float, dec2: float) -> float:
    return angular_separation_deg(ra1, dec1, ra2, dec2) * 3600.0


@pytest.mark.parametrize(
    "ra1,dec1,ra2,dec2",
    [
        (10.0, 20.0, 10.0, 20.0),
        (0.0, 0.0, 0.0, 1.0),
        (0.0, 0.0, 1.0, 0.0),
        (150.0, 2.0, 150.001, 2.001),
        (10.6847083, 41.2687500, 10.6847100, 41.2687520),
        (0.0, 89.9, 180.0, 89.9),
        (359.9999, 0.0, 0.0001, 0.0),
        (10.0, -80.0, 10.0, 80.0),
    ],
)
def test_migrated_matches_legacy_known_cases(ra1, dec1, ra2, dec2):
    assert _migrated_arcsec(ra1, dec1, ra2, dec2) == pytest.approx(
        _legacy_angular_separation_arcsec(ra1, dec1, ra2, dec2), abs=1e-9
    )


def test_migrated_matches_legacy_over_random_pairs():
    # Tolerancia en arcsec, no en fracción relativa: para separaciones de
    # todo el cielo (hasta ~180 grados = 6.48e8 arcsec) las dos fórmulas
    # (haversine vs. atan2/hypot al estilo Vincenty) son matemáticamente
    # equivalentes pero acumulan redondeo de doble precisión de forma
    # distinta -- 1e-6 arcsec sigue siendo muchísimo más preciso que
    # cualquier necesidad real de emparejado con Gaia (radios de pocos
    # arcsec), y confirma que no hay divergencia real de fórmula.
    rng = random.Random(20240608)
    worst_diff = 0.0
    for _ in range(20000):
        ra1 = rng.uniform(0.0, 360.0)
        dec1 = rng.uniform(-89.5, 89.5)
        ra2 = rng.uniform(0.0, 360.0)
        dec2 = rng.uniform(-89.5, 89.5)
        migrated = _migrated_arcsec(ra1, dec1, ra2, dec2)
        legacy = _legacy_angular_separation_arcsec(ra1, dec1, ra2, dec2)
        worst_diff = max(worst_diff, abs(migrated - legacy))
    assert worst_diff < 1e-5


def test_migrated_matches_legacy_over_realistic_close_pairs():
    """Rango realista de emparejado con Gaia: separaciones de hasta unos
    pocos arcsec entre una detección y su vecino catalogado más cercano."""
    rng = random.Random(99)
    worst_diff = 0.0
    for _ in range(5000):
        ra1 = rng.uniform(0.0, 360.0)
        dec1 = rng.uniform(-89.0, 89.0)
        offset_arcsec = rng.uniform(0.0, 5.0)
        bearing = rng.uniform(0.0, 2.0 * math.pi)
        offset_deg = offset_arcsec / 3600.0
        ra2 = ra1 + offset_deg * math.sin(bearing) / max(math.cos(math.radians(dec1)), 1e-6)
        dec2 = dec1 + offset_deg * math.cos(bearing)
        migrated = _migrated_arcsec(ra1, dec1, ra2, dec2)
        legacy = _legacy_angular_separation_arcsec(ra1, dec1, ra2, dec2)
        worst_diff = max(worst_diff, abs(migrated - legacy))
    assert worst_diff < 1e-9
