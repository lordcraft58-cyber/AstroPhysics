"""Prueba de red real contra el servicio SIMBAD.

Se salta explícitamente si la consulta real falla por falta de
conectividad -- no es una razón para fallar la suite, es una limitación
conocida del entorno donde se ejecute (mismo patrón que
`test_gaia_network.py`: un proxy de salida puede aceptar la conexión TCP
y aun así devolver un error a nivel de servicio para hosts fuera de su
lista de permitidos)."""
from __future__ import annotations

import pytest

from astrophysics_suite.catalogs.simbad import resolve_object_coordinates


def test_resolve_object_coordinates_against_a_real_well_known_object():
    result = resolve_object_coordinates("M 31")
    if result is None:
        pytest.skip("SIMBAD no resolvió 'M 31' -- probablemente sin conectividad real (host fuera de la lista de permitidos del proxy de red)")
    ra, dec, source = result
    # M 31 real: RA ~10.68°, Dec ~41.27° -- tolerancia amplia, solo confirma que no es una coordenada inventada.
    assert 9.0 < ra < 12.0
    assert 40.0 < dec < 43.0
    assert source
