from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition


def _provenance() -> Provenance:
    return Provenance.now(pipeline_version="0.4.0-dev", engine="DetectionEngine", engine_version="1.0")


def test_sky_position_requires_ra_dec_together():
    SkyPosition(x_px=10.0, y_px=20.0)  # sin WCS: válido
    SkyPosition(x_px=10.0, y_px=20.0, ra_deg=312.75, dec_deg=30.7)  # con WCS: válido
    with pytest.raises(ValueError):
        SkyPosition(x_px=10.0, y_px=20.0, ra_deg=312.75)  # dec_deg ausente: inválido


def test_sky_position_has_sky_coordinates():
    assert SkyPosition(x_px=1.0, y_px=1.0).has_sky_coordinates is False
    assert SkyPosition(x_px=1.0, y_px=1.0, ra_deg=1.0, dec_deg=1.0).has_sky_coordinates is True


def test_detection_roundtrip():
    d = Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=128.0, y_px=64.0, ra_deg=312.75, dec_deg=30.7, position_error_arcsec=0.3),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=12.0, elongation=1.1, compactness=0.8, fwhm_px=3.4),
        bands=("HA", "OIII"),
        peak_snr=15.2,
        method="DAOStarFinder",
        provenance=_provenance(),
    )
    restored = Detection.from_dict(d.to_dict())
    assert restored == d
    assert restored.morphology.morphology_class is MorphologyClass.POINT_SOURCE
