from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import SkyPosition
from astrophysics_suite.physics.observables import build_physical_observables

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")


def _q(value, error=None, unit=""):
    return Quantity(value=value, error=error, unit=unit, kind=ValueKind.OBSERVED, method="test")


def _characterization(*, fwhm=None, band_ratios=None) -> CharacterizationResult:
    return CharacterizationResult.create(
        detection_id="D0", position=SkyPosition(x_px=1.0, y_px=1.0), provenance=_PROV,
        fwhm=fwhm, band_ratios=band_ratios or {},
    )


def test_no_inputs_leaves_row_empty_with_every_gap_explained():
    result = build_physical_observables(_characterization())
    assert result.row == {}
    assert not result.has_any
    for key in ("oiii_ha_ratio", "offset_arcsec", "distance_pc", "radius_pc", "velocity_kms"):
        assert key in result.unavailable


def test_band_ratio_is_promoted_when_measured():
    chars = _characterization(band_ratios={"OIII/HA": _q(1.8, error=0.1)})
    result = build_physical_observables(chars)
    assert result.row["oiii_ha_ratio"] == 1.8
    assert result.row["ratio_err"] == 0.1
    assert "oiii_ha_ratio" not in result.unavailable


def test_angular_offset_needs_both_fwhm_and_pixel_scale():
    chars = _characterization(fwhm=_q(4.0, error=0.2, unit="px"))
    without_scale = build_physical_observables(chars)
    assert "offset_arcsec" not in without_scale.row
    assert "sin escala de píxel" in without_scale.unavailable["offset_arcsec"]

    with_scale = build_physical_observables(chars, pixel_scale_arcsec=0.8)
    assert with_scale.row["offset_arcsec"] == 4.0 * 0.8
    assert with_scale.row["offset_err_arcsec"] == 0.2 * 0.8


def test_radius_pc_requires_both_angular_size_and_distance():
    chars = _characterization(fwhm=_q(4.0, unit="px"))
    only_angle = build_physical_observables(chars, pixel_scale_arcsec=1.0)
    assert "radius_pc" not in only_angle.row
    assert "distancia" in only_angle.unavailable["radius_pc"]

    only_distance = build_physical_observables(_characterization(), distance_pc=1000.0)
    assert "radius_pc" not in only_distance.row
    assert "tamaño angular" in only_distance.unavailable["radius_pc"]


def test_radius_pc_computed_from_small_angle_approximation_with_propagated_error():
    chars = _characterization(fwhm=_q(4.0, error=0.2, unit="px"))
    result = build_physical_observables(chars, pixel_scale_arcsec=1.0, distance_pc=1000.0, distance_err_pc=50.0)
    offset_arcsec = 4.0
    expected_radius = offset_arcsec / 206265.0 * 1000.0
    assert abs(result.row["radius_pc"] - expected_radius) < 1e-9
    assert result.row["radius_err_pc"] > 0.0
    assert "radius_pc" not in result.unavailable


def test_distance_without_a_positive_finite_value_is_not_promoted():
    result = build_physical_observables(_characterization(), distance_pc=-5.0)
    assert "distance_pc" not in result.row
    assert "distance_pc" in result.unavailable

    result_nan = build_physical_observables(_characterization(), distance_pc=float("nan"))
    assert "distance_pc" not in result_nan.row


def test_velocity_is_never_derived_from_an_image():
    without = build_physical_observables(_characterization())
    assert "velocity_kms" not in without.row
    assert "espectroscopía" in without.unavailable["velocity_kms"]

    with_velocity = build_physical_observables(_characterization(), velocity_kms=120.0, velocity_err_kms=5.0)
    assert with_velocity.row["velocity_kms"] == 120.0
    assert with_velocity.row["velocity_err_kms"] == 5.0


def test_object_family_flows_through_unchanged():
    result = build_physical_observables(_characterization(), object_family="SNR")
    assert result.object_family == "SNR"


def test_describe_gaps_reports_all_absences_readably():
    result = build_physical_observables(_characterization())
    description = result.describe_gaps()
    assert "distance_pc" in description
    assert "velocity_kms" in description
