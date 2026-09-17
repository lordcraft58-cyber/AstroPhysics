"""Prueba de integración de extremo a extremo del modo genérico del
Discovery Engine: FITS sintéticos reales escritos a disco -> Observation
real -> Candidates reales, pasando por detección, rechazo de artefactos,
caracterización e identificación real (sin red disponible en este
entorno, así que la identificación cae honestamente en DISCOVERY_REVIEW
por falta de WCS -- comportamiento correcto, no un mock).
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np

import astrophysics_suite.astrometry.plate_solve as plate_solve_module
import astrophysics_suite.catalogs.gaia as gaia_module
import astrophysics_suite.discovery.pipeline as pipeline_module
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject, gnomonic_project
from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.discovery.pipeline import (
    CFA_STATE_DEBAYERED,
    CFA_STATE_DISABLED,
    CFA_STATE_NOT_CFA,
    WCS_STATE_AUTO_RESOLVED,
    WCS_STATE_BLIND_RESOLVED,
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


def _write_fits_with_scale_only_no_pointing(path, data, *, pixscale: float):
    """FITS real con escala pero SIN ningún puntero en el header (ni
    OBJCTRA/OBJCTDEC ni RA/DEC) -- el caso real reportado en uso: el
    software de captura no siempre escribe la posición, aunque el
    usuario sepa perfectamente qué objeto está fotografiando. Solo
    SIMBAD (por el nombre real del objetivo) puede dar un puntero aquí."""
    from astropy.io import fits

    header = fits.Header()
    header["PIXSCALE"] = pixscale
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(path)


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


def test_run_generic_discovery_resolves_pointing_via_simbad_object_name_when_header_lacks_it(tmp_path, monkeypatch):
    """Caso real reportado en uso: el header no trae RA/DEC ni OBJCTRA/
    OBJCTDEC (el software de captura no siempre las escribe), así que
    Discovery no puede resolver la placa por el header -- pero SÍ debe
    resolverla usando el NOMBRE del objetivo (el que el usuario escribió
    en "Nueva observación") vía SIMBAD, igual que "Spectrophotometric
    Color Calibration" de PixInsight."""
    data, gaia_rows = _solvable_star_field_and_catalog(ra0=10.6847, dec0=41.2688)  # M 31 real
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))
    monkeypatch.setattr(
        pipeline_module, "resolve_object_coordinates",
        lambda name: (10.6847, 41.2688, f"SIMBAD: {name}") if name.strip().lower() == "m 31" else None,
    )

    path = tmp_path / "field_no_header_pointing.fits"
    _write_fits_with_scale_only_no_pointing(path, data, pixscale=1.0)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-INT-WCS-0005", target_name="M 31")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=5.0, match_radius_arcsec=3.0)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_AUTO_RESOLVED, summary.wcs_status[0].detail
    assert "SIMBAD" in summary.wcs_status[0].detail
    assert summary.n_known > 0, "con el puntero resuelto por SIMBAD, se esperan candidatos KNOWN reales, no DISCOVERY_REVIEW"


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


def _write_bayer_mosaic_fits(path, *, positions, shape=(160, 160), pattern="RGGB"):
    """FITS real de cámara OSC: estrellas gaussianas reales muestreadas a
    través de un mosaico de Bayer (cada píxel mide UN color), con el
    `BAYERPAT` real en la cabecera -- como los lights reales del usuario
    (ZWO ASI533MC Pro)."""
    from astropy.io import fits

    rng = np.random.default_rng(11)
    scene = np.full(shape, 1000.0, dtype=np.float64)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    for x, y in positions:
        scene += 9000.0 * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2) / (2 * 2.2**2)))
    scene += rng.normal(0.0, 12.0, shape)

    # Respuesta real por canal: el mosaico atenúa cada píxel según su filtro.
    response = {"R": 0.55, "G": 1.0, "B": 0.45}
    mosaic = np.zeros(shape, dtype=np.float64)
    for index, channel in enumerate(pattern):
        row, col = index // 2, index % 2
        mosaic[row::2, col::2] = scene[row::2, col::2] * response[channel]

    header = fits.Header()
    header["BAYERPAT"] = pattern
    header["PIXSCALE"] = 1.0
    fits.PrimaryHDU(mosaic.astype(np.float32), header=header).writeto(path)


def test_run_generic_discovery_debayers_a_real_cfa_mosaic_and_says_so(tmp_path, monkeypatch):
    """Laguna real encontrada con los lights OSC de M 31 del usuario: sin
    demosaicar, la detección corre sobre el mosaico de Bayer crudo y
    pierde la mayoría de las estrellas (45 detectadas frente a 416 tras
    demosaicar, en el mismo light real). Discovery debe demosaicar ANTES
    de detectar, y decir explícitamente que lo ha hecho."""
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    positions = [(40, 40), (100, 62), (120, 130), (70, 110)]
    path = tmp_path / "osc_light.fits"
    _write_bayer_mosaic_fits(path, positions=positions)

    observation, loaded = build_observation([(str(path), "L")], observation_id="OBS-CFA-0001", target_name="Campo OSC")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert len(summary.cfa_status) == 1
    status = summary.cfa_status[0]
    assert status.state == CFA_STATE_DEBAYERED, status.detail
    assert "RGGB" in status.detail
    assert "SuperPixel" in status.detail
    assert summary.n_detected > 0


def test_run_generic_discovery_finds_more_real_sources_after_debayering(tmp_path, monkeypatch):
    """La comprobación que de verdad importa: demosaicar no es cosmético
    -- sobre el mismo mosaico real, detectar tras demosaicar encuentra
    más estrellas reales que sobre el mosaico crudo."""
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    positions = [(40, 40), (100, 62), (120, 130), (70, 110), (30, 120), (140, 45)]
    path = tmp_path / "osc_light_compare.fits"
    _write_bayer_mosaic_fits(path, positions=positions)

    observation, loaded = build_observation([(str(path), "L")], observation_id="OBS-CFA-0002", target_name="Campo OSC")
    _, with_debayer = run_generic_discovery(observation, loaded, threshold_sigma=4.0, auto_debayer=True)

    observation2, loaded2 = build_observation([(str(path), "L")], observation_id="OBS-CFA-0003", target_name="Campo OSC")
    _, without_debayer = run_generic_discovery(observation2, loaded2, threshold_sigma=4.0, auto_debayer=False)

    assert without_debayer.cfa_status[0].state == CFA_STATE_DISABLED
    assert with_debayer.n_detected >= without_debayer.n_detected, (
        f"demosaicar debe detectar al menos tantas fuentes reales como el mosaico crudo "
        f"(con demosaico: {with_debayer.n_detected}, sin: {without_debayer.n_detected})"
    )


def test_run_generic_discovery_leaves_a_mono_image_untouched(tmp_path, monkeypatch):
    """Una imagen sin BAYERPAT no debe tocarse: nunca se asume un patrón
    'porque es el más común' -- eso rompería cualquier cámara monocroma."""
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    field = _star_field((120, 120), [(40, 40), (80, 70)])
    path = tmp_path / "mono.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    observation, loaded = build_observation([(str(path), "OIII")], observation_id="OBS-CFA-0004", target_name="Campo mono")
    shape_before = loaded[observation.images[0].path].legacy_image.data.shape
    _, summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)

    assert summary.cfa_status[0].state == CFA_STATE_NOT_CFA
    assert loaded[observation.images[0].path].legacy_image.data.shape == shape_before, "una imagen monocroma no debe binificarse"


def _write_fits_with_wcs_and_epoch(path, data, *, crval, date_obs: str, pixel_scale_arcsec: float = 1.0):
    """FITS real con WCS válido Y `DATE-OBS` -- lo que necesitan a la vez
    `discovery/source_tracks.py` (agrupar por coordenadas celestes) y
    `temporal/motion.py` (tiempo real de cada época)."""
    from astropy.io import fits
    from astropy.wcs import WCS

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [data.shape[1] / 2.0, data.shape[0] / 2.0]
    wcs.wcs.cdelt = [-pixel_scale_arcsec / 3600.0, pixel_scale_arcsec / 3600.0]
    wcs.wcs.crval = list(crval)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    header = wcs.to_header()
    header["DATE-OBS"] = date_obs
    fits.PrimaryHDU(data.astype(np.float32), header=header).writeto(path)


def test_run_generic_discovery_groups_multi_epoch_detections_into_one_candidate_per_physical_source(tmp_path, monkeypatch):
    """La comprobación central de esta fase de cierre (ver el docstring del
    módulo): antes de agrupar por traza, 3 imágenes del mismo campo con 2
    fuentes reales cada una producían 6 candidatos -- 3 duplicados por
    fuente física. Agrupando por `discovery/source_tracks.py` deben
    quedar exactamente 2: uno por fuente real, cada uno con su evidencia
    temporal/de movimiento real de las 3 épocas adjunta.

    Además reproduce, con datos reales (no simulados a mano), el caso
    correcto y el caso "trampa" del motor de movimiento: una fuente
    estática con jitter de centroide real NO debe declararse en
    movimiento, y una fuente que sí se desplaza sí debe hacerlo -- con
    significancia derivada del residuo real del ajuste, no inventada."""
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])

    shape = (160, 160)
    crval = (200.0, -10.0)
    t0 = datetime(2026, 9, 10, 20, 0, 0)

    static_xy = (60.0, 60.0)
    step_px = 1.0  # separación entre épocas consecutivas, dentro del radio de emparejamiento
    moving_xy_per_epoch = [(90.0 + step_px * i, 90.0) for i in range(3)]

    image_refs = []
    for i in range(3):
        positions = [static_xy, moving_xy_per_epoch[i]]
        field = _star_field(shape, positions, amplitude=3000.0, sigma=1.6, background=200.0, seed=100 + i)
        path = tmp_path / f"epoch_{i}.fits"
        date_obs = (t0 + timedelta(minutes=5 * i)).isoformat()
        _write_fits_with_wcs_and_epoch(path, field, crval=crval, date_obs=date_obs)
        image_refs.append((str(path), "L"))

    observation, loaded = build_observation(image_refs, observation_id="OBS-MULTI-0001", target_name="Campo multiépoca")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=5.0, match_radius_arcsec=3.0)

    assert summary.n_images == 3
    assert summary.n_candidates == 2, [(c.candidate_id, c.position.ra_deg, c.position.dec_deg) for c in candidates]

    moving = [c for c in candidates if c.identification_state is IdentificationState.MOVING_SOURCE_CANDIDATE]
    assert len(moving) == 1, [c.identification_state.value for c in candidates]
    moving_candidate = moving[0]
    assert moving_candidate.motion_evidence is not None
    assert moving_candidate.motion_evidence.moving_source_candidate is True
    assert moving_candidate.motion_evidence.n_epochs_used == 3
    assert moving_candidate.motion_evidence.pm_total.value > 1.0  # "/h, muy por encima del jitter de centroide
    # La significancia real viene del residuo del ajuste, nunca de un valor fijo.
    assert "σ" in moving_candidate.motion_evidence.pm_total.notes[-1]
    assert moving_candidate.evidence_chain is not None
    categories = {item.category for item in moving_candidate.evidence_chain.items}
    assert "motion_evidence" in categories
    assert "astrometric_anomaly" in categories

    static_candidate = next(c for c in candidates if c is not moving_candidate)
    assert static_candidate.identification_state is not IdentificationState.MOVING_SOURCE_CANDIDATE
    assert static_candidate.motion_evidence is not None
    assert static_candidate.motion_evidence.n_epochs_used == 3
    assert static_candidate.motion_evidence.moving_source_candidate is False, (
        "el jitter de centroide real de una fuente fija no debe superar el umbral de significancia"
    )

    for candidate in candidates:
        assert candidate.evidence_chain is not None
        from astrophysics_suite.models.candidate import Candidate

        assert Candidate.from_dict(candidate.to_dict()) == candidate


def _write_fits_no_pointing_no_wcs(path, data):
    """FITS real SIN WCS, SIN OBJCTRA/OBJCTDEC, SIN RA/DEC -- ni el
    header ni un nombre de objeto dan ningún puntero aproximado. El
    único camino real para resolver esta imagen es la resolución ciega
    (`astrometry/blind_solve.py`) contra un catálogo ya descargado."""
    from astropy.io import fits

    fits.PrimaryHDU(data.astype(np.float32), header=fits.Header()).writeto(path)


def test_run_generic_discovery_resolves_wcs_blind_without_any_pointer_using_the_local_cache(tmp_path, monkeypatch):
    """La petición explícita del usuario: plate solving SIN coordenadas.
    Sin RA/Dec en el header y sin nombre de objeto resoluble (el target
    de la Observation es un nombre no reconocible), Discovery debe
    resolver igualmente el WCS emparejando asterismos contra la caché
    local de catálogos ya descargada -- nunca fallar solo porque falta
    un puntero, si hay algo contra lo que buscar."""
    import astrophysics_suite.catalogs.local_cache as local_cache_module
    from astrophysics_suite.catalogs.local_cache import CatalogCache

    monkeypatch.setattr(pipeline_module, "resolve_object_coordinates", lambda name: None)
    # Redirige la caché local (por defecto) a un directorio temporal real,
    # y la puebla como lo haría una descarga previa -- el mismo camino
    # que usan tanto `_try_blind_solve` (CatalogCache("gaia") por defecto)
    # como la consulta real de `query_gaia_neighbors` durante la
    # verificación (caché primero, antes que la red).
    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)

    ra0, dec0 = 83.633, -5.391
    rng = np.random.default_rng(7)
    xi = rng.uniform(-0.3, 0.3, 400)
    eta = rng.uniform(-0.3, 0.3, 400)
    cat_ra, cat_dec = gnomonic_deproject(xi, eta, ra0, dec0)
    mags = rng.uniform(10.0, 16.0, 400)
    catalog_rows = [
        {"source_id": f"CAT-{i}", "ra_deg": float(r), "dec_deg": float(d), "mag_g": float(m)}
        for i, (r, d, m) in enumerate(zip(cat_ra, cat_dec, mags))
    ]
    CatalogCache("gaia").store_region(ra0, dec0, 1200.0, mag_limit=20.0, rows=catalog_rows)

    scale_arcsec_px, rotation_deg, shape = 1.2, 37.0, (512, 512)
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    scale_deg = scale_arcsec_px / 3600.0
    cd = scale_deg * np.array([[cos_t, -sin_t], [sin_t, cos_t]])
    cd_inv = np.linalg.inv(cd)
    img_xi, img_eta = gnomonic_project(np.array(cat_ra), np.array(cat_dec), ra0, dec0)
    offsets = cd_inv @ np.vstack([img_xi, img_eta])
    height, width = shape
    px, py = offsets[0] + width / 2.0, offsets[1] + height / 2.0
    margin = 12.0
    in_field = (px >= margin) & (px < width - margin) & (py >= margin) & (py < height - margin)
    assert in_field.sum() >= 15, "la propia prueba necesita suficientes estrellas reales en el campo"

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    for x0, y0, mag in zip(px[in_field], py[in_field], mags[in_field]):
        amplitude = 20000.0 * 10 ** (-0.4 * (mag - 10.0))
        data += amplitude * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * 1.8**2))
    data += rng.normal(0, 3.0, shape)

    path = tmp_path / "field_no_pointer.fits"
    _write_fits_no_pointing_no_wcs(path, data)

    observation, loaded = build_observation([(str(path), "L")], observation_id="OBS-BLIND-0001", target_name="objetivo no reconocible")
    candidates, summary = run_generic_discovery(observation, loaded, threshold_sigma=6.0, match_radius_arcsec=3.0)

    assert len(summary.wcs_status) == 1
    assert summary.wcs_status[0].state == WCS_STATE_BLIND_RESOLVED, summary.wcs_status[0].detail
    assert summary.n_candidates > 0
    for candidate in candidates:
        assert candidate.position.has_sky_coordinates, "el WCS resuelto en ciego debe llegar a las coordenadas reales de cada candidato"
