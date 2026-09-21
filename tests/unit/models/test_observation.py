from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.models.observation import ImageRef, Observation


def _sample_observation() -> Observation:
    return Observation.create(
        observation_id="OBS-0001",
        target_name="NGC 6960",
        created_at=datetime(2026, 9, 16, tzinfo=timezone.utc),
        images=(
            ImageRef(path="/data/oiii.fits", band="OIII", role="science", pixel_scale_arcsec=1.2, has_wcs=True, sha256="a" * 64),
            ImageRef(path="/data/ha.fits", band="HA", role="science", pixel_scale_arcsec=1.2, has_wcs=True, sha256="b" * 64),
        ),
        instrument="ASI533",
    )


def test_observation_roundtrip():
    obs = _sample_observation()
    restored = Observation.from_dict(obs.to_dict())
    assert restored == obs
    assert restored.images[0].band == "OIII"


def test_observation_schema_version_stamped():
    obs = _sample_observation()
    assert obs.schema_version >= 1
    assert obs.to_dict()["schema_version"] == obs.schema_version


def test_observation_epoch_optional():
    obs = _sample_observation()
    assert obs.epoch is None
    assert obs.to_dict()["epoch"] is None
    assert Observation.from_dict(obs.to_dict()).epoch is None
