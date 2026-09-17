"""Tests reales de anomaly/vector.py -- las siete dimensiones del
AnomalyVector, cada una una Quantity con procedencia o NO DISPONIBLE con
motivo. Cubre en particular el error científico propio detectado y
corregido durante cacac21: `_photometric_anomaly`/`_spectral_anomaly`
antes devolvían significancia de detección / |log10(ratio)| en vez de
una desviación frente a una expectativa real -- habría marcado como
anómala cualquier estrella brillante o cualquier relación distinta de 1."""
from __future__ import annotations

from astrophysics_suite.anomaly.vector import build_anomaly_vector
from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import SkyPosition
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence
from astrophysics_suite.physics.constraints import evaluate_consistency
from astrophysics_suite.physics.inference import infer_physical_inference

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")


def _q(value, error=None, unit=""):
    return Quantity(value=value, error=error, unit=unit, kind=ValueKind.OBSERVED, method="test")


def _characterization(*, fwhm=None, band_flux=None, band_ratios=None) -> CharacterizationResult:
    return CharacterizationResult.create(
        detection_id="D0", position=SkyPosition(x_px=1.0, y_px=1.0), provenance=_PROV,
        fwhm=fwhm, band_flux=band_flux or {}, band_ratios=band_ratios or {},
    )


def test_all_dimensions_are_not_available_with_no_inputs():
    vector = build_anomaly_vector(detection_id="D0", characterization=_characterization())
    for dimension in ("photometric", "morphological", "spectral", "temporal", "astrometric", "spatial", "physical"):
        quantity = getattr(vector, dimension)
        assert not quantity.is_available, dimension
        assert quantity.reference  # siempre con motivo concreto


def test_photometric_anomaly_requires_both_measured_flux_and_expectation():
    chars = _characterization(band_flux={"HA": _q(1000.0, error=50.0, unit="adu")})
    without_expectation = build_anomaly_vector(detection_id="D0", characterization=chars)
    assert not without_expectation.photometric.is_available
    assert "flujo medido" in without_expectation.photometric.reference

    with_expectation = build_anomaly_vector(
        detection_id="D0", characterization=chars, expected_band_flux={"HA": 500.0},
    )
    assert with_expectation.photometric.is_available
    assert with_expectation.photometric.value == abs(1000.0 - 500.0) / 50.0


def test_photometric_anomaly_never_reports_flux_over_error_as_the_anomaly():
    # Regresión directa del bug de cacac21: una estrella brillante y bien
    # medida (flujo/error alto) NO debe salir como "anómala" solo por ser
    # brillante -- necesita una expectativa de la que desviarse.
    bright_and_precisely_measured = _characterization(band_flux={"HA": _q(50000.0, error=10.0, unit="adu")})
    result = build_anomaly_vector(detection_id="D0", characterization=bright_and_precisely_measured)
    assert not result.photometric.is_available


def test_spectral_anomaly_requires_both_measured_ratio_and_expectation():
    chars = _characterization(band_ratios={"OIII/HA": _q(1.8, error=0.1)})
    without_expectation = build_anomaly_vector(detection_id="D0", characterization=chars)
    assert not without_expectation.spectral.is_available

    with_expectation = build_anomaly_vector(
        detection_id="D0", characterization=chars, expected_band_ratios={"OIII/HA": 0.3},
    )
    assert with_expectation.spectral.is_available
    assert with_expectation.spectral.value == abs(1.8 - 0.3) / 0.1


def test_spectral_anomaly_never_flags_a_ratio_merely_for_not_being_one():
    # Regresión directa del bug de cacac21: |log10(ratio)| marcaba como
    # anómala cualquier relación distinta de 1, sin ninguna referencia.
    chars = _characterization(band_ratios={"OIII/HA": _q(5.0, error=0.2)})
    result = build_anomaly_vector(detection_id="D0", characterization=chars)
    assert not result.spectral.is_available


def test_morphological_anomaly_needs_a_field_reference():
    chars = _characterization(fwhm=_q(8.0, unit="px"))
    without_field = build_anomaly_vector(detection_id="D0", characterization=chars)
    assert not without_field.morphological.is_available

    with_field = build_anomaly_vector(
        detection_id="D0", characterization=chars, field_median_fwhm_px=3.5, field_fwhm_scatter_px=0.5,
    )
    assert with_field.morphological.is_available
    assert with_field.morphological.value == abs(8.0 - 3.5) / 0.5


def test_temporal_dimension_reflects_variability_significance():
    variable = TemporalEvidence.create(
        detection_id="D0", n_epochs=5, variable_candidate=True,
        provenance=Provenance.now(pipeline_version="test", engine="temporal.variability", engine_version="1.0"),
        brightness_change=_q(2.0, error=0.25, unit="value/epoch"),
    )
    result = build_anomaly_vector(detection_id="D0", characterization=_characterization(), temporal=variable)
    assert result.temporal.is_available
    assert result.temporal.value == 2.0 / 0.25


def test_temporal_dimension_not_available_without_a_temporal_engine_run():
    result = build_anomaly_vector(detection_id="D0", characterization=_characterization(), temporal=None)
    assert not result.temporal.is_available
    assert "no se ejecutó" in result.temporal.reference


def test_astrometric_dimension_reflects_motion_significance():
    moving = MotionEvidence.create(
        detection_id="D0", n_epochs_used=3, moving_source_candidate=True,
        provenance=Provenance.now(pipeline_version="test", engine="temporal.motion", engine_version="1.0"),
        pm_total=_q(24.0, error=3.6, unit="arcsec/hour"),
    )
    result = build_anomaly_vector(detection_id="D0", characterization=_characterization(), motion=moving)
    assert result.astrometric.is_available
    assert abs(result.astrometric.value - 24.0 / 3.6) < 1e-9


def test_physical_dimension_delegates_to_the_consistency_result():
    row = {"radius_pc": 5.0, "velocity_kms": 120.0, "age_yr": 1.0, "age_err_yr": 0.01}
    inferred = infer_physical_inference({"radius_pc": 5.0, "velocity_kms": 120.0}, detection_id="D0", object_family="SNR")
    consistency = evaluate_consistency(row, inferred, sigma_threshold=4.0)
    result = build_anomaly_vector(detection_id="D0", characterization=_characterization(), consistency=consistency)
    assert result.physical.is_available
    assert result.physical.value >= 4.0


def test_spatial_dimension_passes_through_when_provided_and_absent_otherwise():
    absent = build_anomaly_vector(detection_id="D0", characterization=_characterization())
    assert not absent.spatial.is_available

    provided = _q(6.5, unit="sigma")
    present = build_anomaly_vector(detection_id="D0", characterization=_characterization(), spatial=provided)
    assert present.spatial is provided


def test_roundtrip():
    from astrophysics_suite.models.anomaly import AnomalyVector

    vector = build_anomaly_vector(detection_id="D0", characterization=_characterization())
    assert AnomalyVector.from_dict(vector.to_dict()) == vector
