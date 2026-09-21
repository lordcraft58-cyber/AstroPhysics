"""Verifica que el adaptador de la Fase 4 es compatible con una salida
REAL de discovery_scan_observation() (no solo con un dict inventado a
mano) -- ejecuta el pipeline heredado de verdad sobre una imagen
sintética y traduce una fila real.
"""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.core.enums import IdentificationState
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.legacy_adapter import (
    ArtifactRejectedRow,
    candidate_from_discovery_workspace_row,
    identification_state_from_discovery_workspace_row,
)


def _synthetic_field_with_one_source(shape=(96, 96)):
    rng = np.random.default_rng(7)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, 100.0, dtype=np.float32)
    field += 900.0 * np.exp(-((xx - 48) ** 2 + (yy - 48) ** 2) / (2 * 2.0**2))
    field += rng.normal(0, 3.0, shape)
    return field.astype(np.float32)


def test_adapter_handles_real_discovery_workspace_row(aps, tmp_path):
    image = _synthetic_field_with_one_source()
    image_path = tmp_path / "field_OIII.fits"
    aps._write_minimal_fits_2d(image_path, image)

    payload = aps.discovery_scan_observation([str(image_path)], str(tmp_path / "out"), snr_min=4.0)
    assert payload["candidates"], "el escaneo sintético debe producir al menos un candidato"

    reviewable = [r for r in payload["candidates"] if r.get("evidence_state") != "REJECTED_ARTIFACT"]
    assert reviewable, "debe haber al menos una fila no rechazada como artefacto para probar el adaptador"

    row = reviewable[0]
    candidate = candidate_from_discovery_workspace_row(row, observation_id="OBS-TEST-0001", pipeline_version="57.0.0")

    assert isinstance(candidate, Candidate)
    assert candidate.observation_id == "OBS-TEST-0001"
    assert candidate.position.x_px == pytest.approx(float(row["x"]))
    assert candidate.identification_state in set(IdentificationState)


def test_artifact_rejected_row_raises_instead_of_silently_producing_a_candidate():
    row = {"evidence_state": "REJECTED_ARTIFACT", "artifact_reason": "elongación extrema (traza)", "x": 1.0, "y": 1.0}
    with pytest.raises(ArtifactRejectedRow):
        candidate_from_discovery_workspace_row(row, observation_id="OBS-0001", pipeline_version="57.0.0")


@pytest.mark.parametrize(
    ("row", "expected"),
    [
        ({"catalog_state": "KNOWN_GAIA", "anomaly_state": "NONE"}, IdentificationState.KNOWN),
        ({"catalog_state": "KNOWN_GAIA", "anomaly_state": "MORPHOLOGY_OUTLIER"}, IdentificationState.KNOWN_VARIANT),
        ({"catalog_state": "UNMATCHED_GAIA", "anomaly_state": "NONE"}, IdentificationState.UNMATCHED),
        ({"catalog_state": "UNMATCHED_GAIA", "anomaly_state": "MORPHOLOGY_OUTLIER"}, IdentificationState.ANOMALOUS),
        ({"discovery_state": "SCIENCE_CANDIDATE"}, IdentificationState.DISCOVERY_REVIEW),
        ({"discovery_state": "QUALITY_LIMITED"}, IdentificationState.DISCOVERY_REVIEW),
    ],
)
def test_identification_state_mapping_table(row, expected):
    assert identification_state_from_discovery_workspace_row(row) is expected
