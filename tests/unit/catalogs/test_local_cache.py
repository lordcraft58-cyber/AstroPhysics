"""Pruebas de la caché local de catálogos en disco
(`catalogs.local_cache`) -- SQLite real escrito a disco real, nunca
simulado: es justo la parte cuya persistencia hay que comprobar."""
from __future__ import annotations

import pytest

from astrophysics_suite.catalogs.local_cache import CatalogCache, download_field_to_cache


def _rows_around(ra: float, dec: float, n: int = 5) -> list[dict]:
    return [
        {"source_id": f"GAIA-{i}", "ra_deg": ra + i * 0.001, "dec_deg": dec + i * 0.001, "mag_g": 14.0 + i * 0.2}
        for i in range(n)
    ]


def test_stores_and_serves_real_sources_from_disk(tmp_path):
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    stored = cache.store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0))
    assert stored == 5
    assert (tmp_path / "gaia.sqlite3").exists(), "la caché debe existir de verdad en disco"

    # Una instancia NUEVA (proceso distinto, en la práctica) debe leer lo ya guardado.
    reopened = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    rows, covered = reopened.query_neighbors(10.0, 41.0, radius_arcsec=10.0)
    assert covered is True
    assert len(rows) >= 1
    assert rows[0]["source_id"] == "GAIA-0", "debe devolver la más cercana primero"


def test_uncovered_position_reports_not_covered_instead_of_empty_result(tmp_path):
    """La distinción central: "no descargado" NUNCA debe parecer "no hay
    nada ahí" -- es el mismo error epistémico que se corrigió en
    `catalogs/gaia.py` con Gaia inalcanzable."""
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    cache.store_region(10.0, 41.0, 600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0))

    rows, covered = cache.query_neighbors(200.0, -30.0, radius_arcsec=5.0)  # otro punto del cielo
    assert rows == []
    assert covered is False, "una zona nunca descargada debe declararse NO cubierta, no 'vacía'"


def test_an_empty_but_really_downloaded_region_is_covered(tmp_path):
    """"Descargué este campo y de verdad no hay nada catalogado" es un
    resultado científico real -- y debe distinguirse de no haberlo
    descargado nunca."""
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    cache.store_region(120.0, 5.0, 600.0, mag_limit=20.0, rows=[])

    rows, covered = cache.query_neighbors(120.0, 5.0, radius_arcsec=5.0)
    assert rows == []
    assert covered is True, "la región SÍ se descargó: vacía es una respuesta real, no una pregunta sin responder"


def test_edge_of_a_region_is_not_served_as_complete(tmp_path):
    """Justo en el borde de lo descargado, el radio de búsqueda se sale
    de la zona cubierta -- servir ahí daría un resultado incompleto sin
    avisar, así que se declara NO cubierto."""
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    cache.store_region(10.0, 41.0, 600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0))

    # a 599" del centro, con un radio de búsqueda de 30": parte del círculo cae fuera
    _, covered = cache.query_neighbors(10.0, 41.0 + 599.0 / 3600.0, radius_arcsec=30.0)
    assert covered is False


def test_respects_the_search_radius_and_magnitude_limit(tmp_path):
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    cache.store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=[
        {"source_id": "cerca-brillante", "ra_deg": 10.0, "dec_deg": 41.0, "mag_g": 12.0},
        {"source_id": "cerca-debil", "ra_deg": 10.0001, "dec_deg": 41.0, "mag_g": 19.5},
        {"source_id": "lejos", "ra_deg": 10.5, "dec_deg": 41.0, "mag_g": 12.0},
    ])

    rows, _ = cache.query_neighbors(10.0, 41.0, radius_arcsec=5.0)
    assert {row["source_id"] for row in rows} == {"cerca-brillante", "cerca-debil"}, "la lejana queda fuera del radio"

    bright_only, _ = cache.query_neighbors(10.0, 41.0, radius_arcsec=5.0, mag_limit=15.0)
    assert {row["source_id"] for row in bright_only} == {"cerca-brillante"}


def test_regions_and_describe_report_the_real_state(tmp_path):
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    assert "Sin datos descargados" in cache.describe()

    cache.store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0, n=7))
    regions = cache.regions()
    assert len(regions) == 1
    assert regions[0].n_sources == 7
    assert regions[0].ra_deg == pytest.approx(10.0)
    description = cache.describe()
    assert "7 fuentes" in description
    assert str(tmp_path) in description


def test_clear_removes_everything_for_that_catalog(tmp_path):
    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    cache.store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0))
    cache.clear()
    assert cache.regions() == []
    _, covered = cache.query_neighbors(10.0, 41.0, radius_arcsec=5.0)
    assert covered is False


def test_download_field_stores_nothing_when_the_service_is_unavailable(tmp_path, monkeypatch):
    """Si Gaia no responde, NO se guarda una región vacía: eso haría que
    `covers()` mintiera diciendo que ese campo ya está cubierto."""
    import astrophysics_suite.catalogs.gaia as gaia_module

    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])
    monkeypatch.setattr(gaia_module, "last_gaia_availability", lambda: (False, "Error 403: Host not in allowlist"))

    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    ok, detail = download_field_to_cache(10.0, 41.0, 3600.0, cache=cache)

    assert ok is False
    assert "403" in detail
    assert cache.regions() == [], "una descarga fallida no debe dejar una región fantasma"


def test_download_field_stores_the_real_rows_on_success(tmp_path, monkeypatch):
    import astrophysics_suite.catalogs.gaia as gaia_module

    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: _rows_around(10.0, 41.0, n=4))
    monkeypatch.setattr(gaia_module, "last_gaia_availability", lambda: (True, ""))

    cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    ok, detail = download_field_to_cache(10.0, 41.0, 3600.0, cache=cache)

    assert ok is True
    assert "4 fuentes" in detail
    rows, covered = cache.query_neighbors(10.0, 41.0, radius_arcsec=30.0)
    assert covered is True
    assert len(rows) >= 1


def test_query_gaia_neighbors_serves_from_cache_without_touching_the_network(tmp_path, monkeypatch):
    """La razón de ser de la caché: con el campo ya descargado, un
    análisis con cientos de detecciones no hace NINGUNA consulta de red."""
    import astrophysics_suite.catalogs.gaia as gaia_module
    from astrophysics_suite.catalogs.local_cache import CatalogCache as RealCache

    cache_path = tmp_path / "gaia.sqlite3"
    RealCache("gaia", path=cache_path).store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=_rows_around(10.0, 41.0))

    monkeypatch.setattr(
        gaia_module, "_query_local_cache",
        lambda ra, dec, *, radius_arcsec, mag_limit, max_rows: RealCache("gaia", path=cache_path).query_neighbors(
            ra, dec, radius_arcsec=radius_arcsec, mag_limit=mag_limit, max_rows=max_rows),
    )

    def _network_must_not_be_called(*args, **kwargs):
        raise AssertionError("con el campo en caché no se debe consultar la red")

    monkeypatch.setattr(gaia_module, "_legacy_crossmatch_gaia_safe", _network_must_not_be_called)

    rows = gaia_module.query_gaia_neighbors(10.0, 41.0, radius_arcsec=30.0)
    assert len(rows) >= 1
    available, _ = gaia_module.last_gaia_availability()
    assert available is True, "servido desde la caché cuenta como catálogo consultado de verdad"


def test_query_gaia_neighbors_falls_back_to_the_network_outside_the_cached_field(tmp_path, monkeypatch):
    import astrophysics_suite.catalogs.gaia as gaia_module

    monkeypatch.setattr(gaia_module, "_query_local_cache", lambda *a, **k: ([], False))
    calls: list[tuple] = []

    def _fake_network(ra, dec, *, radius_arcsec, mag_limit, max_rows):
        calls.append((ra, dec))
        return {"state": "OBSERVABLE", "gaia_available": True, "sources": [{"source_id": "red", "ra_deg": ra, "dec_deg": dec, "mag_g": 15.0}]}

    monkeypatch.setattr(gaia_module, "_legacy_crossmatch_gaia_safe", _fake_network)

    rows = gaia_module.query_gaia_neighbors(200.0, -30.0, radius_arcsec=5.0)
    assert len(calls) == 1, "fuera de lo descargado SÍ hay que consultar la red"
    assert rows[0]["source_id"] == "red"


def test_a_broken_cache_file_degrades_to_not_covered_instead_of_raising(tmp_path, monkeypatch):
    """Un archivo de caché corrupto debe comportarse como "este campo no
    está descargado" y dejar que la consulta siga por red -- un problema
    con la caché nunca debe romper un análisis entero."""
    import astrophysics_suite.catalogs.gaia as gaia_module
    import astrophysics_suite.catalogs.local_cache as local_cache_module

    broken = tmp_path / "gaia.sqlite3"
    broken.write_bytes(b"esto no es una base de datos SQLite")
    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)

    rows, covered = gaia_module._query_local_cache(10.0, 41.0, radius_arcsec=5.0, mag_limit=20.0, max_rows=25)

    assert rows == []
    assert covered is False, "una caché ilegible es 'no lo sé', nunca una excepción que aborte el análisis"
