from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.physics.inference import infer_physical_inference


def test_infer_physical_inference_mixed_kinds_from_real_row():
    row = {
        "ratio": 2.0,
        "ratio_err": 0.1,
        "offset_arcsec": 5.0,
        "offset_err_arcsec": 0.5,
        "velocity_kms": 120.0,
        "velocity_err_kms": 10.0,
        "radius_pc": 1.2,
        "radius_err_pc": 0.1,
    }
    inf = infer_physical_inference(row, detection_id="DET-0001", object_family="SNR", distance_pc=1500.0, distance_err_pc=100.0)

    assert inf.detection_id == "DET-0001"
    assert inf.domain_valid is True
    assert "log10_oiii_over_ha" in inf.parameters
    assert inf.parameters["log10_oiii_over_ha"].kind is ValueKind.OBSERVED

    # postshock_temperature_K y age_yr requieren un modelo -> MODEL_INFERENCE.
    assert inf.parameters["postshock_temperature_K"].kind is ValueKind.MODEL_INFERENCE
    assert inf.parameters["postshock_temperature_K"].value > 0
    assert "age_yr" in inf.parameters
    assert inf.parameters["age_yr"].kind is ValueKind.MODEL_INFERENCE

    # el resumen a nivel de inferencia debe reflejar los modelos realmente usados.
    assert "sedov_uniform_medium" in inf.model_hypotheses or "spherical" in inf.model_hypotheses
    assert inf.model_id  # no vacío: al menos un modelo participó


def test_infer_physical_inference_empty_row_is_not_domain_valid():
    inf = infer_physical_inference({}, detection_id="DET-0002", object_family="unknown")
    assert inf.parameters == {}
    assert inf.domain_valid is False
    assert inf.model_id == ""


def test_infer_physical_inference_never_derives_velocity_without_model():
    """Un ratio por sí solo (sin velocity_kms) nunca debe producir una
    velocidad -- eso sería exactamente la sobre-inferencia que el encargo
    original prohíbe explícitamente."""
    row = {"ratio": 3.0, "ratio_err": 0.2}
    inf = infer_physical_inference(row, detection_id="DET-0003", object_family="unknown")
    assert "velocity_kms" not in inf.parameters
    assert "postshock_temperature_K" not in inf.parameters
    assert inf.parameters["log10_oiii_over_ha"].kind is ValueKind.OBSERVED


def test_infer_physical_inference_roundtrip():
    row = {"velocity_kms": 100.0, "velocity_err_kms": 5.0}
    inf = infer_physical_inference(row, detection_id="DET-0004", object_family="shock_front")
    from astrophysics_suite.models.physical import PhysicalInference

    restored = PhysicalInference.from_dict(inf.to_dict())
    assert restored == inf
