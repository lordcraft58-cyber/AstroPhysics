from __future__ import annotations

from astrophysics_suite.anomaly.physical_tension import physical_anomaly_quantity
from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.physics.inference import infer_physical_inference


def _q(value, error=None, unit="", method="test"):
    return Quantity(value=value, error=error, unit=unit, kind=ValueKind.OBSERVED, method=method)


def test_no_tension_when_parameters_are_self_consistent():
    """Réplica del propio test de consistencia embebido en el código
    heredado (selftest / _v46_regression_tests): una relación de Sedov
    internamente consistente no debe marcarse como tensión física."""
    row = {"radius_pc": 1.0, "velocity_kms": 100.0}
    inf = infer_physical_inference(row, detection_id="DET-0001", object_family="SNR")
    age = inf.parameters["age_yr"]
    row_with_age = dict(row, age_yr=age.value)
    parameters = dict(inf.parameters)
    parameters["age_yr"] = age

    result = physical_anomaly_quantity(row_with_age, parameters, min_sigma=4.0)
    assert not result.is_available


def test_flags_tension_when_age_is_wildly_inconsistent():
    """PhysicalConstraintEngine.evaluate() lee radius_pc/velocity_kms/age_yr
    de `estimates` (el segundo argumento), no de `row`. `infer_physical_
    parameters()` nunca copia los observables crudos (radius_pc,
    velocity_kms) a su propia salida -- solo sus magnitudes derivadas
    (postshock_temperature_K, age_yr). Por eso, para ejercer esta
    comprobación de verdad, hay que añadir radius_pc/velocity_kms a
    `parameters` explícitamente (lo que este wrapper permite porque acepta
    `parameters` como argumento independiente); la ruta de producción
    real (DiscoveryEvidenceEngine.evaluate_rows, ver
    tests/unit/evidence/test_fusion.py) nunca lo hace y por tanto nunca
    puede disparar esta comprobación -- un hallazgo documentado en
    docs/audit/08-FASE6-MOTORES-RESTANTES.md, seccion 7."""
    row = {"radius_pc": 1.0, "velocity_kms": 100.0}
    inf = infer_physical_inference(row, detection_id="DET-0002", object_family="SNR")
    parameters = dict(inf.parameters)
    parameters["radius_pc"] = _q(1.0, error=0.05, unit="pc")
    parameters["velocity_kms"] = _q(100.0, error=5.0, unit="km/s")
    # Una edad absurdamente distinta de la predicha por radio+velocidad.
    parameters["age_yr"] = _q(1.0, error=0.01, unit="yr")

    result = physical_anomaly_quantity(row, parameters, min_sigma=4.0)
    assert result.is_available
    assert result.value >= 4.0
    assert any("Sedov" in note for note in result.notes)


def test_flags_reference_comparison_anomaly():
    parameters = {"postshock_temperature_K": _q(5_000_000.0, error=100_000.0, unit="K")}
    reference = {"postshock_temperature_K": {"value": 1_000_000.0, "sigma": 200_000.0, "source": "literature_sample"}}

    result = physical_anomaly_quantity({}, parameters, reference=reference, min_sigma=4.0)
    assert result.is_available
    assert any("referencia" in note for note in result.notes)


def test_negative_ratio_is_a_measurement_issue_not_a_physical_anomaly():
    """PhysicalConstraintEngine distingue explícitamente un problema de
    medición (ratio negativo) de una tensión física real; no deben
    confundirse en el resumen."""
    parameters: dict[str, Quantity] = {}
    result = physical_anomaly_quantity({"ratio": -1.0}, parameters, min_sigma=4.0)
    assert not result.is_available
