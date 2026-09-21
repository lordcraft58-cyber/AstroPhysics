"""`resolve_object_coordinates` -- contrato puro, sin red real: se
sustituye la clase `Simbad` completa (no solo `query_object`) porque el
backend TAP moderno de astroquery.simbad puede tocar red ya en la
construcción/configuración del cliente, no solo al consultar -- igual
de exigente que mockear en el punto real más bajo posible, pero sin que
un intento de red real (bloqueado en este sandbox) contamine el test."""
from __future__ import annotations

import pytest

import legacy.AstroPhysicsSuite_v57_3_COMMERCIAL as legacy
from astrophysics_suite.catalogs.simbad import resolve_object_coordinates


class _FakeResultTable:
    def __init__(self, rows: dict[str, list]):
        self._rows = rows
        self.colnames = list(rows.keys())

    def __len__(self) -> int:
        return len(next(iter(self._rows.values()))) if self._rows else 0

    def __getitem__(self, key):
        return self._rows[key]


def _fake_simbad_factory(query_object_impl):
    class _FakeSimbad:
        def __init__(self):
            self.ROW_LIMIT = None

        def add_votable_fields(self, *args, **kwargs):
            return None

        def query_object(self, name):
            return query_object_impl(name)

    return _FakeSimbad


def test_resolve_object_coordinates_returns_none_for_empty_name():
    assert resolve_object_coordinates("") is None
    assert resolve_object_coordinates("   ") is None
    assert resolve_object_coordinates(None) is None


def test_resolve_object_coordinates_returns_real_ra_dec_on_success(monkeypatch):
    def query_object_impl(name):
        return _FakeResultTable({"ra": [10.6847083], "dec": [41.26875], "otype": ["G"]})

    monkeypatch.setattr(legacy, "Simbad", _fake_simbad_factory(query_object_impl))

    result = resolve_object_coordinates("M 31")
    assert result is not None
    ra, dec, source = result
    assert ra == pytest.approx(10.6847083)
    assert dec == pytest.approx(41.26875)
    assert "SIMBAD" in source


def test_resolve_object_coordinates_returns_none_when_simbad_has_no_result(monkeypatch):
    monkeypatch.setattr(legacy, "Simbad", _fake_simbad_factory(lambda name: None))
    assert resolve_object_coordinates("Objeto que no existe en ningún catálogo real xyz123") is None


def test_resolve_object_coordinates_never_raises_when_the_network_call_fails(monkeypatch):
    def raising_query_object(name):
        raise ConnectionError("simulado: servicio SIMBAD no disponible")

    monkeypatch.setattr(legacy, "Simbad", _fake_simbad_factory(raising_query_object))
    assert resolve_object_coordinates("M 42") is None


def test_resolve_object_coordinates_tries_known_messier_aliases(monkeypatch):
    """`_normalise_object_query` (heredado) ya conoce alias conservadores
    para M31/M42/M27/NGC6960 -- confirma que de verdad se usan, no solo
    el nombre crudo, consultando con un nombre que solo el alias
    resuelve."""
    seen_queries = []

    def query_object_impl(name):
        seen_queries.append(name)
        if name == "M 31":
            return _FakeResultTable({"ra": [10.6847083], "dec": [41.26875]})
        return None

    monkeypatch.setattr(legacy, "Simbad", _fake_simbad_factory(query_object_impl))
    result = resolve_object_coordinates("m31")
    assert result is not None
    assert "M 31" in seen_queries
