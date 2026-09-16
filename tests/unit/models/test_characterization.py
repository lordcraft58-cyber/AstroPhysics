from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import SkyPosition


def test_characterization_roundtrip_with_band_dicts():
    result = CharacterizationResult.create(
        detection_id="DET-0001",
        position=SkyPosition(x_px=128.0, y_px=64.0, ra_deg=312.75, dec_deg=30.7),
        provenance=Provenance.now(pipeline_version="0.4.0-dev", engine="CharacterizationEngine", engine_version="1.0"),
        fwhm=Quantity(value=3.4, error=0.2, unit="px", kind=ValueKind.OBSERVED, method="gaussian_fit"),
        band_flux={
            "HA": Quantity(value=1200.0, error=50.0, unit="ADU", kind=ValueKind.OBSERVED, method="aperture_photometry"),
            "OIII": Quantity(value=900.0, error=40.0, unit="ADU", kind=ValueKind.OBSERVED, method="aperture_photometry"),
        },
        band_ratios={
            "OIII_HA": Quantity(value=0.75, error=0.05, unit="dimensionless", kind=ValueKind.PROXY, method="flux_ratio"),
        },
        extra={
            "filament_length_arcsec": Quantity(value=42.0, error=3.0, unit="arcsec", kind=ValueKind.OBSERVED, method="ridge_length"),
        },
    )
    restored = CharacterizationResult.from_dict(result.to_dict())
    assert restored == result
    assert restored.band_flux["HA"].value == 1200.0
    assert restored.extra["filament_length_arcsec"].kind is ValueKind.OBSERVED


def test_characterization_optional_fields_default_empty():
    result = CharacterizationResult.create(detection_id="DET-0002", position=SkyPosition(x_px=1.0, y_px=1.0))
    assert result.band_flux == {}
    assert result.size is None
    assert result.provenance is None
    restored = CharacterizationResult.from_dict(result.to_dict())
    assert restored == result
