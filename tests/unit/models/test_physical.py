from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.physical import PhysicalInference


def test_physical_inference_mixed_kinds_per_parameter():
    """Dentro de la misma inferencia, distintos parámetros pueden tener
    distinto estatus epistémico -- una distancia asumida (OBSERVED, en el
    sentido de "dato de entrada dado") y una edad derivada (MODEL_INFERENCE)."""
    inf = PhysicalInference.create(
        detection_id="DET-0001",
        object_family="SNR",
        model_id="sedov_uniform_medium",
        model_hypotheses=("spherical", "adiabatic", "uniform_medium"),
        domain_valid=True,
        parameters={
            "distance_pc": Quantity(value=1500.0, error=100.0, unit="pc", kind=ValueKind.OBSERVED, method="literature"),
            "age_yr": Quantity(value=12000.0, error=2000.0, unit="yr", kind=ValueKind.MODEL_INFERENCE, method="sedov_uniform_medium", reference="grid-v2"),
        },
        provenance=Provenance.now(pipeline_version="0.4.0-dev", engine="PhysicalEngine", engine_version="1.0", grid_sha256="c" * 64),
    )
    restored = PhysicalInference.from_dict(inf.to_dict())
    assert restored == inf
    assert restored.parameters["distance_pc"].kind is ValueKind.OBSERVED
    assert restored.parameters["age_yr"].kind is ValueKind.MODEL_INFERENCE


def test_physical_inference_invalid_domain_still_serializable():
    """domain_valid=False no debe impedir construir/serializar el registro
    -- el motor de evidencia decide qué hacer con ello, el modelo de datos
    solo lo transporta fielmente."""
    inf = PhysicalInference.create(detection_id="DET-0002", object_family="unknown", domain_valid=False)
    assert inf.model_id == ""
    assert inf.parameters == {}
    assert PhysicalInference.from_dict(inf.to_dict()) == inf
