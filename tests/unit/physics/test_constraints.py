"""Tests reales de physics/constraints.py -- la corrección de la brecha
de contrato documentada en el propio módulo: `PhysicalConstraintEngine`
buscaba radius_pc/velocity_kms en `estimates` (inferido) cuando en
realidad son observables MEDIDOS que viven en `row`. Ver el docstring
del módulo para la medición original (0 comprobaciones -> 2)."""
from __future__ import annotations

from astrophysics_suite.physics.constraints import evaluate_consistency, physical_tension_quantity
from astrophysics_suite.physics.inference import infer_physical_inference


def test_no_observables_and_no_inference_evaluates_nothing():
    result = evaluate_consistency({}, None)
    assert result.issues == ()
    assert "Sedov age-radius-velocity" in result.not_evaluated
    assert "Strong-shock T-v" in result.not_evaluated

    tension = physical_tension_quantity(result)
    assert not tension.is_available


def test_measured_radius_and_velocity_without_inferred_age_cannot_evaluate_sedov():
    # radius_pc/velocity_kms medidos, pero sin PhysicalInference no hay
    # edad ni temperatura post-choque con las que contrastarlos.
    result = evaluate_consistency({"radius_pc": 5.0, "velocity_kms": 120.0}, None)
    assert result.issues == ()
    assert "Sedov age-radius-velocity" in result.not_evaluated


def test_self_consistent_row_reaches_the_engine_but_is_tautological():
    # La brecha real (ver docstring del módulo): con el contrato explícito,
    # las comprobaciones SÍ se alcanzan (issues no vacío). La edad usada es
    # la MISMA fórmula 0.4*R/v que produjo la inferencia -- observado y
    # predicho salen idénticos -- pero `infer_physical_inference` no da
    # una incertidumbre a age_yr, así que el motor no puede ni fabricar
    # un z-score: z_score=None es el resultado correcto (no un 0.0
    # inventado), y se advierte aparte en not_evaluated que es tautológica.
    row = {"radius_pc": 5.0, "velocity_kms": 120.0}
    inferred = infer_physical_inference(row, detection_id="D0", object_family="SNR")
    result = evaluate_consistency(row, inferred)
    assert len(result.issues) >= 1
    sedov = next(i for i in result.issues if i.constraint == "Sedov age-radius-velocity")
    assert sedov.z_score is None
    assert not sedov.flagged
    assert not sedov.is_physical_tension
    assert sedov.detail["observed_age_yr"] == sedov.detail["predicted_age_yr"]
    # Documentado explícitamente como tautológico pese a haberse evaluado.
    assert "age_yr" in result.not_evaluated
    assert "no puede detectar tensión" in result.not_evaluated["age_yr"]


def test_independent_measured_age_that_contradicts_inference_flags_real_tension():
    # La comprobación que de verdad demuestra que la brecha está cerrada:
    # una edad MEDIDA de forma independiente (p.ej. histórica), muy distinta
    # de la que predice Sedov a partir de radio+velocidad, debe producir una
    # tensión física real y significativa -- no z=0.
    row = {"radius_pc": 5.0, "velocity_kms": 120.0, "age_yr": 1.0, "age_err_yr": 0.01}
    inferred = infer_physical_inference({"radius_pc": 5.0, "velocity_kms": 120.0}, detection_id="D0", object_family="SNR")
    result = evaluate_consistency(row, inferred, sigma_threshold=4.0)
    sedov = next(i for i in result.issues if i.constraint == "Sedov age-radius-velocity")
    assert sedov.z_score is not None
    assert abs(sedov.z_score) >= 4.0
    assert sedov.is_physical_tension
    assert "age_yr" not in result.not_evaluated  # medida independiente: ya no es tautológica

    tension = physical_tension_quantity(result)
    assert tension.is_available
    assert tension.value >= 4.0
    assert any("Sedov" in note for note in tension.notes)


def test_missing_required_observable_is_reported_by_name():
    result = evaluate_consistency({"velocity_kms": 120.0}, None)
    assert "radius_pc" in result.not_evaluated
    assert "ausente" in result.not_evaluated["radius_pc"]


def test_physical_tension_quantity_reports_zero_when_all_evaluated_issues_are_consistent():
    row = {"radius_pc": 5.0, "velocity_kms": 120.0}
    inferred = infer_physical_inference(row, detection_id="D0", object_family="SNR")
    result = evaluate_consistency(row, inferred)
    tension = physical_tension_quantity(result)
    # Se evaluó (issues no vacío) y ninguna tensión superó el umbral: 0.0,
    # no "no disponible" -- son estados distintos y no deben confundirse.
    assert tension.is_available
    assert tension.value == 0.0
