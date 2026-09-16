"""Prueba de integración de extremo a extremo del modo genérico del
Discovery Engine: FITS sintéticos reales escritos a disco -> Observation
real -> Candidates reales, pasando por detección, rechazo de artefactos,
caracterización e identificación real (sin red disponible en este
entorno, así que la identificación cae honestamente en DISCOVERY_REVIEW
por falta de WCS -- comportamiento correcto, no un mock).
"""
from __future__ import annotations

import numpy as np

from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.discovery.pipeline import run_generic_discovery
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
