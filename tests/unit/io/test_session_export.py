"""Prueba end-to-end real (no simulada): candidatos REALES producidos
por `run_generic_discovery` sobre un FITS sintético -> `save_session` a
disco -> `load_session` de vuelta, confirmando que cada `Candidate`
(con su vector de anomalía, cadena de evidencia y procedencia reales)
sobrevive sin pérdida -- el mismo nivel de exigencia que
`test_fits_writer.py` aplicó a la escritura de imágenes."""
from __future__ import annotations

import json
from datetime import datetime, timezone

import numpy as np
import pytest

from astrophysics_suite.io.fits_loader import build_observation
from astrophysics_suite.io.session_export import SCHEMA_VERSION, load_session, save_session
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _real_session(tmp_path):
    """Observación + candidatos REALES: mismo generador de campo que
    `tests/integration/test_generic_discovery_pipeline.py`."""
    from astrophysics_suite.discovery.pipeline import run_generic_discovery

    rng = np.random.default_rng(5)
    yy, xx = np.mgrid[0:120, 0:120]
    field = np.full((120, 120), 100.0, dtype=np.float32)
    for x, y in [(30, 30), (70, 80), (95, 40)]:
        field += 1200.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, field.shape)
    field = field.astype(np.float32)

    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)
    observation, loaded = build_observation([(str(path), "HA")], observation_id="OBS-SESSION-0001", target_name="Campo de prueba")
    candidates, _summary = run_generic_discovery(observation, loaded, threshold_sigma=4.0)
    assert candidates, "la prueba necesita al menos un candidato real para tener algo que guardar"
    return observation, candidates


def test_save_and_load_session_roundtrips_real_candidates_without_loss(tmp_path):
    observation, candidates = _real_session(tmp_path)
    out_path = tmp_path / "session.apssession.json"

    save_session(str(out_path), project_name="Proyecto de prueba", observations=[observation], candidates=candidates)
    loaded = load_session(str(out_path))

    assert loaded.project_name == "Proyecto de prueba"
    assert len(loaded.observations) == 1
    assert loaded.observations[0] == observation
    assert len(loaded.candidates) == len(candidates)
    for original, reloaded in zip(candidates, loaded.candidates):
        assert reloaded == original


def test_save_session_writes_real_readable_json_with_expected_shape(tmp_path):
    observation, candidates = _real_session(tmp_path)
    out_path = tmp_path / "session.json"

    save_session(str(out_path), project_name="P", observations=[observation], candidates=candidates)

    raw = json.loads(out_path.read_text(encoding="utf-8"))
    assert raw["schema_version"] == SCHEMA_VERSION
    assert raw["project_name"] == "P"
    assert len(raw["candidates"]) == len(candidates)
    assert raw["provenance"]["engine"] == "io.session_export"
    assert "saved_at" in raw


def test_save_session_creates_missing_parent_directories(tmp_path):
    observation, candidates = _real_session(tmp_path)
    out_path = tmp_path / "nested" / "output" / "session.json"

    save_session(str(out_path), project_name="P", observations=[observation], candidates=candidates)

    assert out_path.exists()


def test_save_session_overwrite_false_raises_on_existing_file(tmp_path):
    observation, candidates = _real_session(tmp_path)
    out_path = tmp_path / "session.json"
    save_session(str(out_path), project_name="P", observations=[observation], candidates=candidates)

    with pytest.raises(FileExistsError):
        save_session(str(out_path), project_name="P", observations=[observation], candidates=candidates, overwrite=False)


def test_load_session_rejects_an_incompatible_schema_version(tmp_path):
    out_path = tmp_path / "future_session.json"
    out_path.write_text(json.dumps({"schema_version": 999, "candidates": [], "observations": []}), encoding="utf-8")

    with pytest.raises(ValueError, match="esquema"):
        load_session(str(out_path))


def test_save_session_on_an_empty_project_still_produces_a_valid_reloadable_file(tmp_path):
    out_path = tmp_path / "empty_session.json"

    save_session(str(out_path), project_name="Vacío", observations=[], candidates=[])
    loaded = load_session(str(out_path))

    assert loaded.project_name == "Vacío"
    assert loaded.observations == ()
    assert loaded.candidates == ()


def _wcs_solution():
    from astrophysics_suite.astrometry.optical_wcs import build_wcs_from_optics

    return build_wcs_from_optics(
        center_ra_deg=11.087505, center_dec_deg=41.412641,
        pixel_scale_arcsec=1.0355, image_shape=(3008, 3008), rotation_deg=17.5,
    )


def _zeropoint_fit():
    from astrophysics_suite.photometry.calibration import ZeropointFit

    return ZeropointFit(
        zeropoint_mag=24.31, zeropoint_uncertainty_mag=0.042,
        n_stars_used=18, n_stars_rejected=3,
        residuals_mag=(0.01, -0.02, 0.005), rms_residual_mag=0.031,
        used_mask=(True, True, False, True),
    )


def test_session_roundtrips_the_wcs_and_zeropoint_of_each_image(tmp_path):
    """El P0 nº9 del usuario: hasta ahora un WCS ajustado a mano o
    construido desde la óptica moría al cerrar la aplicación."""
    out_path = tmp_path / "calibrated_session.json"
    solution, fit = _wcs_solution(), _zeropoint_fit()

    save_session(
        str(out_path), project_name="M31", observations=[], candidates=[],
        wcs_solutions={"/datos/light_0001.fit": solution},
        zeropoint_fits={"/datos/light_0001.fit": fit},
    )
    loaded = load_session(str(out_path))

    restored = loaded.wcs_solutions["/datos/light_0001.fit"]
    assert restored.crval_deg == pytest.approx(solution.crval_deg)
    assert restored.crpix_px == solution.crpix_px
    np.testing.assert_allclose(restored.cd_matrix_deg_per_px, solution.cd_matrix_deg_per_px, rtol=0, atol=0)
    # y sigue apuntando al mismo sitio del cielo de verdad, no solo en los números
    assert restored.pixel_to_sky(100.0, 250.0) == pytest.approx(solution.pixel_to_sky(100.0, 250.0))

    restored_fit = loaded.zeropoint_fits["/datos/light_0001.fit"]
    assert restored_fit == fit  # dataclass completa, máscara de sigma-clip incluida


def test_session_without_calibrations_loads_them_empty_not_invented(tmp_path):
    out_path = tmp_path / "plain_session.json"
    save_session(str(out_path), project_name="P", observations=[], candidates=[])
    loaded = load_session(str(out_path))
    assert loaded.wcs_solutions == {}
    assert loaded.zeropoint_fits == {}


def test_old_v1_sessions_still_load(tmp_path):
    """Compatibilidad real hacia atrás: las sesiones ya guardadas por el
    usuario son v1 y no traían calibraciones -- deben seguir abriéndose."""
    from astrophysics_suite.core.provenance import Provenance

    out_path = tmp_path / "v1_session.json"
    out_path.write_text(json.dumps({
        "schema_version": 1,
        "project_name": "Sesión antigua",
        "saved_at": datetime.now(timezone.utc).isoformat(),
        "provenance": Provenance.now(pipeline_version="", engine="io.session_export", engine_version="1.0").to_dict(),
        "observations": [],
        "candidates": [],
    }), encoding="utf-8")

    loaded = load_session(str(out_path))
    assert loaded.project_name == "Sesión antigua"
    assert loaded.wcs_solutions == {}
    assert loaded.zeropoint_fits == {}
