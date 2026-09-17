"""Prueba end-to-end del job en hilo de fondo contra FITS sintéticos
reales -- confirma que la GUI puede consumir progreso/resultado sin
bloquear, y que cancelar de verdad detiene el trabajo."""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
from services.discovery_service import DiscoveryJob, DiscoveryParams


def _star_field(shape, positions, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, 100.0, dtype=np.float32)
    for x, y in positions:
        field += 900.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def _wait_for_events(job: DiscoveryJob, kinds: set[str], timeout: float = 10.0) -> list:
    collected = []
    deadline = time.monotonic() + timeout
    seen_kinds = set()
    while time.monotonic() < deadline:
        events = job.poll()
        collected.extend(events)
        seen_kinds.update(e.kind for e in events)
        if seen_kinds & kinds:
            return collected
        time.sleep(0.02)
    raise AssertionError(f"Timeout esperando eventos {kinds}; vistos: {seen_kinds}")


def test_discovery_job_runs_in_background_and_reports_progress(tmp_path):
    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)

    job = DiscoveryJob(target_name="Campo de prueba", images=[(str(path), "OIII")], params=DiscoveryParams(threshold_sigma=4.0))
    job.start()

    events = _wait_for_events(job, {"done", "error"})
    kinds = [e.kind for e in events]
    assert "progress" in kinds, "debe reportar progreso antes de terminar"
    assert kinds[-1] == "done"

    done_event = events[-1]
    assert done_event.observation is not None
    assert done_event.summary is not None
    assert done_event.summary.n_detected >= 2
    assert len(done_event.candidates) == done_event.summary.n_candidates


def test_discovery_job_completes_when_input_path_differs_from_its_resolved_form(tmp_path, monkeypatch):
    """Regresión del error real reportado en uso: "Descubrimiento falló:
    '<ruta>'" en TODOS los análisis en Windows. Causa raíz (ver
    docs/audit/25-FIX-DISCOVERY-KEYERROR-RUTA.md): `build_observation`
    indexaba `loaded_images` por la ruta cruda que pasó el llamador, pero
    `run_generic_discovery` la busca por `ImageRef.path` (ya resuelta por
    `Path(path).resolve()`) -- si el texto de las dos rutas no coincide
    exactamente (siempre el caso en Windows, donde `QFileDialog` devuelve
    rutas con '/' mientras pathlib normaliza a '\\'; aquí reproducido de
    forma determinista y multiplataforma con una ruta relativa), la
    búsqueda lanzaba un `KeyError` real, capturado genéricamente por
    `except Exception` y mostrado al usuario sin ningún contexto más que
    la ruta misma."""
    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_relative.fits"
    _write_minimal_fits_2d(path, field)

    monkeypatch.chdir(tmp_path)
    relative_path = path.name
    assert relative_path != str(Path(relative_path).resolve())

    job = DiscoveryJob(
        target_name="Campo con ruta relativa", images=[(relative_path, "OIII")], params=DiscoveryParams(threshold_sigma=4.0)
    )
    job.start()

    events = _wait_for_events(job, {"done", "error"})
    done_event = events[-1]
    if done_event.kind == "error":
        raise AssertionError(f"Discovery falló con la ruta relativa (bug reproducido): {done_event.message}")
    assert done_event.kind == "done"
    assert done_event.summary.n_detected >= 2


def _star_field_with_wcs(path, shape, positions, *, crval=(150.0, 2.0), crpix=None, pixel_scale_arcsec=1.0, seed=5):
    """Escribe un FITS real con un WCS TAN válido (astropy) -- a
    diferencia de `_write_minimal_fits_2d`, que solo escribe CDELT sin
    CRVAL/CRPIX/CTYPE y por tanto nunca produce un WCS que
    `legacy.load_fits` reconozca como válido."""
    from astropy.io import fits
    from astropy.wcs import WCS

    field = _star_field(shape, positions, seed=seed)
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = list(crpix) if crpix is not None else [shape[1] / 2.0, shape[0] / 2.0]
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
    wcs.wcs.crval = list(crval)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    fits.PrimaryHDU(field, header=wcs.to_header()).writeto(path)
    return wcs


def test_discovery_job_reaches_known_and_unmatched_with_real_wcs_and_mocked_gaia(tmp_path, monkeypatch):
    """"Test Discovery con WCS válido" -- a diferencia de la cobertura ya
    existente de `classify_against_gaia_neighbors` (pura, sin red) y de
    `test_run_generic_discovery_end_to_end` (sin WCS -> DISCOVERY_REVIEW),
    esta prueba corre la cadena COMPLETA que usa la GUI
    (DiscoveryJob -> build_observation -> run_generic_discovery ->
    detección real -> identify_detection) contra un FITS con un WCS TAN
    real y verifica que se alcanzan KNOWN (estrella emparejada) y
    UNMATCHED (estrella sin fuente Gaia cercana) -- nunca inventando
    coordenadas ni un estado que la lógica real no produjo."""
    import astrophysics_suite.catalogs.gaia as gaia_module

    shape = (120, 120)
    matched_xy = (40.0, 40.0)
    unmatched_xy = (80.0, 80.0)
    wcs = _star_field_with_wcs(tmp_path / "field_wcs.fits", shape, [matched_xy, unmatched_xy])
    matched_ra, matched_dec = wcs.all_pix2world(matched_xy[0], matched_xy[1], 0)

    def fake_query_gaia_neighbors(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        # Solo "conoce" la estrella emparejada -- la otra debe quedar UNMATCHED,
        # nunca inventada como conocida.
        if abs(ra_deg - float(matched_ra)) < 1e-3 and abs(dec_deg - float(matched_dec)) < 1e-3:
            return [{"ra_deg": float(matched_ra), "dec_deg": float(matched_dec), "source_id": "GAIA-TEST-1", "mag_g": 14.5}]
        return []

    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", fake_query_gaia_neighbors)

    job = DiscoveryJob(
        target_name="Campo con WCS real",
        images=[(str(tmp_path / "field_wcs.fits"), "OIII")],
        params=DiscoveryParams(threshold_sigma=4.0, match_radius_arcsec=3.0),
    )
    job.start()

    events = _wait_for_events(job, {"done", "error"})
    done_event = events[-1]
    if done_event.kind == "error":
        raise AssertionError(f"Discovery falló con WCS real: {done_event.message}")

    from astrophysics_suite.core.enums import IdentificationState

    states = {c.identification_state for c in done_event.candidates}
    assert IdentificationState.KNOWN in states, f"se esperaba al menos un candidato KNOWN; estados vistos: {states}"
    assert IdentificationState.UNMATCHED in states, f"se esperaba al menos un candidato UNMATCHED; estados vistos: {states}"
    for candidate in done_event.candidates:
        if candidate.identification_state is IdentificationState.KNOWN:
            assert candidate.catalog_matches[0].catalog_id == "GAIA-TEST-1"


def test_discovery_job_does_not_crash_when_gaia_service_call_raises(tmp_path, monkeypatch):
    """"no rompe si Gaia no está disponible" -- simula el fallo real que
    puede pasar (la llamada de red subyacente de astroquery lanzando, no
    una lista vacía) en el mismo punto donde ya lo atrapa el código
    heredado (`crossmatch_gaia_safe`, con `except Exception` real) y
    confirma que Discovery sigue completando de extremo a extremo,
    degradando a DISCOVERY_REVIEW -- no un `ConnectionError` inventado
    directamente en `query_gaia_neighbors`, que rompería un contrato que
    esa función no tiene (siempre delega el manejo de errores en
    `crossmatch_gaia_safe`, nunca lanza ella misma).

    DISCOVERY_REVIEW y no UNMATCHED: bug real encontrado al probar con
    FITS reales de M 31 en un entorno sin red hacia Gaia -- los 141
    candidatos reales salían UNMATCHED (\"sin fuentes Gaia en el radio\"),
    una afirmación falsa porque Gaia nunca llegó a responder. Declarar
    UNMATCHED sin haber podido consultar el catálogo confunde \"se
    consultó y no había nada cerca\" con \"no se pudo comprobar\" -- la
    ausencia de respuesta nunca debe leerse como ausencia de fuente."""
    astroquery_gaia = pytest.importorskip("astroquery.gaia", reason="astroquery no instalado en este entorno")

    shape = (80, 80)
    _star_field_with_wcs(tmp_path / "field_gaia_down.fits", shape, [(35.0, 35.0)])

    def raising_launch_job(*args, **kwargs):
        raise ConnectionError("simulado: servicio Gaia no disponible")

    # Se parchea la llamada de red real DENTRO del `try/except` ya
    # existente de `crossmatch_gaia_safe` (legacy) -- no la función que lo
    # envuelve, para probar de verdad que ESE manejo de errores funciona,
    # en vez de sustituirlo por uno artificial.
    monkeypatch.setattr(astroquery_gaia.Gaia, "launch_job", raising_launch_job)

    job = DiscoveryJob(target_name="Campo sin Gaia", images=[(str(tmp_path / "field_gaia_down.fits"), "OIII")], params=DiscoveryParams(threshold_sigma=4.0))
    job.start()

    events = _wait_for_events(job, {"done", "error"})
    done_event = events[-1]
    if done_event.kind == "error":
        raise AssertionError(f"Discovery no debe fallar cuando Gaia no está disponible: {done_event.message}")

    from astrophysics_suite.core.enums import IdentificationState

    assert all(c.identification_state is IdentificationState.DISCOVERY_REVIEW for c in done_event.candidates)
    for candidate in done_event.candidates:
        assert candidate.catalog_non_matches[0].reason.startswith("Gaia no disponible")


def test_discovery_job_cancel_stops_before_completion(tmp_path):
    field = _star_field((96, 96), [(30, 30)])
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)

    job = DiscoveryJob(target_name="Campo cancelado", images=[(str(path), "HA")])
    job.cancel()  # cancelar antes de start(): debe detenerse en el primer chequeo
    job.start()

    events = _wait_for_events(job, {"cancelled", "done", "error"})
    assert events[-1].kind == "cancelled"
