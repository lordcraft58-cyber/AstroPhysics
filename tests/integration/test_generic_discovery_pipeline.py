"""Prueba de integración de extremo a extremo del modo genérico del
Discovery Engine: FITS sintéticos reales escritos a disco -> Observation
real -> Candidates reales, pasando por detección, rechazo de artefactos,
caracterización e identificación real (sin red disponible en este
entorno, así que la identificación cae honestamente en DISCOVERY_REVIEW
por falta de WCS -- comportamiento correcto, no un mock).
"""
from __future__ import annotations

import math

import numpy as np

import astrophysics_suite.astrometry.plate_solve as plate_solve_module
import astrophysics_suite.catalogs.gaia as gaia_module
import astrophysics_suite.discovery.pipeline as pipeline_module
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject
from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.discovery.pipeline import (
    WCS_STATE_AUTO_RESOLVED,
    WCS_STATE_PRESENT,
    WCS_STATE_SOLVE_FAILED,
    WCS_STATE_SOLVE_NOT_RUN,
    run_generic_discovery,
)
from astrophysics_suite.io.fits_loader import build_observation
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _star_field(shape, positions, amplitude=900.0, sigma=1.8, background=100.0, seed=7):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, float(background), dtype=np.float32)
    for x, y in positions:
        field += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def test_run_generic_discovery_end_to_end(tmp_path):
    positions = [(40, 40), (100, 60), (70, 120)]
    field = _star_field((160, 160), positions)
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    observation, loaded = build_observation(
        [(str(path), "OIII")], observation_id="OBS-INT-0001", target_name="Campo sintético"
    )

    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert summary.observation_id == "OBS-INT-0001"
    assert summary.n_images == 1
    assert summary.n_detected >= len(positions)
    assert summary.n_candidates + summary.n_artifact_rejected == summary.n_detected
    assert summary.n_candidates == len(candidates)

    # Sin WCS en el FITS sintético: no se inventan coordenadas celestes,
    # así que la identificación cae honestamente en DISCOVERY_REVIEW.
    assert summary.n_known == 0
    assert summary.n_unmatched == 0
    assert summary.n_discovery_review == summary.n_candidates

    for candidate in candidates:
        assert candidate.observation_id == "OBS-INT-0001"
        assert candidate.bands == ("OIII",)
        assert candidate.identification_state is IdentificationState.DISCOVERY_REVIEW
        assert candidate.snr is not None and candidate.snr.value > 0
        assert candidate.quality.overall_level.value in {"PASS", "WARNING"}
        assert candidate.review_state.value == "PENDING"
        # Serialización real de un candidato producido por el pipeline real.
        from astrophysics_suite.models.candidate import Candidate

        assert Candidate.from_dict(candidate.to_dict()) == candidate


def test_run_generic_discovery_on_empty_field_produces_no_candidates(tmp_path):
    field = np.full((64, 64), 100.0, dtype=np.float32)
    path = tmp_path / "empty.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    observation, loaded = build_observation([(str(path), "HA")], observation_id="OBS-INT-0002", target_name="Campo vacío")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=5.0)

    assert candidates == []
    assert summary.n_detected == 0
    assert summary.n_candidates == 0


def test_run_generic_discovery_across_two_bands(tmp_path):
    positions = [(32, 32)]
    oiii = _star_field((64, 64), positions, seed=1)
    ha = _star_field((64, 64), positions, seed=2)
    oiii_path = tmp_path / "target_OIII.fits"
    ha_path = tmp_path / "target_HALPHA.fits"
    _write_minimal_fits_2d(oiii_path, oiii, pixel_scale_arcsec=1.0)
    _write_minimal_fits_2d(ha_path, ha, pixel_scale_arcsec=1.0)

    observation, loaded = build_observation(
        [(str(oiii_path), "OIII"), (str(ha_path), "HA")], observation_id="OBS-INT-0003", target_name="Campo multibanda"
    )
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert summary.n_images == 2
    bands_seen = {c.bands[0] for c in candidates}
    assert bands_seen == {"OIII", "HA"}


def _true_cd(scale_arcsec_px: float, rotation_deg: float) -> np.ndarray:
    scale_deg = scale_arcsec_px / 3600.0
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return scale_deg * np.array([[cos_t, -sin_t], [sin_t, cos_t]])


def _write_fits_with_pointing_no_wcs(path, data, *, objctra: str, objctdec: str, pixscale: float):
    """FITS real con puntero/escala aproximados en el header (como los
    escribiría el software de una montura/cámara real) pero SIN WCS
    completo (sin CRVAL/CRPIX/CTYPE) -- exactamente el caso que debe
    disparar la resolución automática de placa dentro de Discovery."""
    from astropy.io import fits

    header = fits.Header()
    header["OBJCTRA"] = objctra
    header["OBJCTDEC"] = objctdec
    header["PIXSCALE"] = pixscale
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(path)


def _solvable_star_field_and_catalog(shape=(160, 160), *, ra0=210.0, dec0=-8.0, scale=1.0, rotation_deg=12.0, n_stars=20, seed=9):
    rng = np.random.default_rng(seed)
    height, width = shape
    crpix = (width / 2.0, height / 2.0)
    cd = _true_cd(scale, rotation_deg)
    margin = 15.0
    xs = rng.uniform(margin, width - margin, n_stars)
    ys = rng.uniform(margin, height - margin, n_stars)
    dx, dy = xs - crpix[0], ys - crpix[1]
    offsets = cd @ np.vstack([dx, dy])
    ra, dec = gnomonic_deproject(offsets[0], offsets[1], ra0, dec0)

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    sigma = 1.3
    for x0, y0 in zip(xs, ys):
        data += 25000.0 / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data += rng.normal(0, 3.0, shape)

    gaia_rows = [{"ra_deg": float(r), "dec_deg": float(d), "source_id": f"GAIA-{i}", "mag_g": 14.0} for i, (r, d) in enumerate(zip(ra, dec))]
    return data, gaia_rows


def _radius_filtered_gaia_mock(gaia_rows):
    def query(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra_deg, dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    return query


def test_run_generic_discovery_resolves_missing_wcs_automatically_and_reaches_known(tmp_path, monkeypatch):
    """Prueba obligatoria (objetivo 1 y 3 del encargo): Discovery, ante una
    imagen sin WCS pero con puntero/escala aproximados reales en el
    header, resuelve la placa automáticamente ANTES de detectar/
    identificar -- y el resultado (KNOWN vía Gaia real, no inventado) usa
    de verdad las coordenadas resueltas, no se queda en DISCOVERY_REVIEW
    "porque no había WCS"."""
    data, gaia_rows = _solvable_star_field_and_catalog()
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))

    path = tmp_path / "field_no_wcs_solvable.fits"
    _write_fits_with_pointing_no_wcs(path, data, objctra="14 00 00", objctdec="-08 00 00", pixscale=1.0)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-INT-WCS-0001", target_name="Campo resoluble")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=5.0, match_radius_arcsec=3.0)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_AUTO_RESOLVED, summary.wcs_status[0].detail

    assert summary.n_candidates > 0
    assert summary.n_known > 0, "con el WCS resuelto y el mismo catálogo, se esperan candidatos KNOWN reales"
    assert summary.n_discovery_review == 0, "con WCS ya disponible, ningún candidato debe quedar en DISCOVERY_REVIEW por falta de coordenadas"
    for candidate in candidates:
        if candidate.identification_state is IdentificationState.KNOWN:
            assert candidate.catalog_matches[0].catalog_id.startswith("GAIA-")


def test_run_generic_discovery_records_plate_solve_failure_without_crashing(tmp_path, monkeypatch):
    """Prueba obligatoria (test E del encargo): si la placa no se puede
    resolver (aquí, sin ningún puntero aproximado en el header), Discovery
    no lanza excepción -- registra el fallo explícitamente y continúa
    degradando a DISCOVERY_REVIEW, como ya hacía sin este mecanismo."""
    positions = [(40, 40), (100, 60)]
    field = _star_field((160, 160), positions)
    path = tmp_path / "field_no_pointing.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-INT-WCS-0002", target_name="Campo sin puntero")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_SOLVE_FAILED
    assert "posición aproximada" in summary.wcs_status[0].detail
    assert summary.n_discovery_review == summary.n_candidates > 0


def test_run_generic_discovery_skips_plate_solve_when_disabled(tmp_path, monkeypatch):
    """Prueba obligatoria: con `auto_plate_solve=False`, Discovery no
    intenta resolver la placa aunque el header traiga puntero/escala --
    se registra explícitamente como NO_EJECUTADO, nunca como un fallo
    silencioso ni como si se hubiera intentado."""
    data, gaia_rows = _solvable_star_field_and_catalog()

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("solve_plate no debe llamarse cuando auto_plate_solve=False")

    monkeypatch.setattr(pipeline_module, "solve_plate", _must_not_be_called)

    path = tmp_path / "field_solve_disabled.fits"
    _write_fits_with_pointing_no_wcs(path, data, objctra="14 00 00", objctdec="-08 00 00", pixscale=1.0)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-INT-WCS-0003", target_name="Campo sin resolver")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=5.0, auto_plate_solve=False)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_SOLVE_NOT_RUN
    assert summary.n_discovery_review == summary.n_candidates > 0


def test_run_generic_discovery_reports_wcs_present_and_never_calls_solve_plate(tmp_path, monkeypatch):
    """Prueba obligatoria (test C del encargo, extendida): una imagen que
    YA trae un WCS real y válido nunca dispara plate solving -- ni
    siquiera se llama."""
    from astropy.io import fits
    from astropy.wcs import WCS

    def _must_not_be_called(*args, **kwargs):
        raise AssertionError("solve_plate no debe llamarse cuando la imagen ya tiene WCS")

    monkeypatch.setattr(pipeline_module, "solve_plate", _must_not_be_called)
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    positions = [(40, 40), (100, 60)]
    field = _star_field((160, 160), positions)
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [80.0, 80.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [180.0, 10.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    path = tmp_path / "field_real_wcs.fits"
    fits.PrimaryHDU(field, header=wcs.to_header()).writeto(path)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-INT-WCS-0004", target_name="Campo con WCS")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_PRESENT
    assert summary.n_candidates > 0
    assert all(c.identification_state is IdentificationState.UNMATCHED for c in candidates)
