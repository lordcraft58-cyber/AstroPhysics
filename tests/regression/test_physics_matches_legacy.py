"""`physics/inference.py::_infer_physical_parameters` +
`physics/constraints.py::_evaluate_physical_constraints` (migrados del
monolito legacy en el cierre sistemático del motor 11/16, informe 99)
deben producir EXACTAMENTE lo mismo que `legacy.infer_physical_
parameters`/`legacy.PhysicalConstraintEngine.evaluate` -- campo a campo,
reimplementación 1:1 sin ningún cambio deliberado de fórmula.
"""
from __future__ import annotations

import pytest

from astrophysics_suite.physics.constraints import _evaluate_physical_constraints
from astrophysics_suite.physics.inference import _infer_physical_parameters
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import PhysicalConstraintEngine as _LegacyPhysicalConstraintEngine
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import infer_physical_parameters as _legacy_infer_physical_parameters

_PARAM_FIELDS = ("value", "error", "unit", "status", "source", "model", "assumptions")


def _assert_inference_matches_legacy(row, **kwargs):
    migrated = _infer_physical_parameters(row, **kwargs)
    legacy = _legacy_infer_physical_parameters(row, **kwargs)

    assert migrated["object_family"] == legacy["object_family"]
    assert sorted(migrated["available"]) == sorted(legacy["available"])
    assert set(migrated["parameters"]) == set(legacy["parameters"])
    for name in migrated["parameters"]:
        migrated_p, legacy_p = migrated["parameters"][name], legacy["parameters"][name]
        for field in _PARAM_FIELDS:
            mv, lv = migrated_p.get(field), legacy_p.get(field)
            if isinstance(mv, float) and isinstance(lv, float):
                if mv != mv and lv != lv:  # ambos NaN
                    continue
                assert mv == pytest.approx(lv, abs=1e-9), f"{name}.{field}: {mv} != {lv}"
            else:
                assert mv == lv, f"{name}.{field}: {mv} != {lv}"
    return migrated


@pytest.mark.parametrize(
    "row",
    [
        {"ratio": 3.2, "ratio_err": 0.1, "offset_arcsec": 12.0, "offset_err_arcsec": 0.5, "velocity_kms": 120.0, "velocity_err_kms": 5.0, "radius_pc": 5.0, "radius_err_pc": 0.2},
        {"velocity_kms": 80.0},
        {"offset_arcsec": 20.0},
        {},
        {"flux_ha_calibrated": 1.5e-14, "flux_oiii": 3.0e-15},
    ],
)
def test_inference_matches_legacy_without_distance(row):
    _assert_inference_matches_legacy(row, object_family="SNR")


def test_inference_matches_legacy_with_distance():
    row = {"offset_arcsec": 15.0, "offset_err_arcsec": 0.3}
    _assert_inference_matches_legacy(row, object_family="SNR", distance_pc=785000.0, distance_err_pc=25000.0)


def test_inference_matches_legacy_with_full_snr_row_including_age():
    row = {"velocity_kms": 120.0, "velocity_err_kms": 5.0, "radius_pc": 5.0, "radius_err_pc": 0.2}
    _assert_inference_matches_legacy(row, object_family="SNR")


def _assert_constraints_match_legacy(row, estimates, *, min_sigma):
    migrated = _evaluate_physical_constraints(row, estimates, min_sigma=min_sigma)
    legacy = _LegacyPhysicalConstraintEngine(min_sigma=min_sigma).evaluate(row, estimates)

    assert migrated["n_physical_tensions"] == legacy["n_physical_tensions"]
    assert migrated["n_measurement_issues"] == legacy["n_measurement_issues"]
    assert len(migrated["issues"]) == len(legacy["issues"])
    for migrated_issue, legacy_issue in zip(migrated["issues"], legacy["issues"]):
        assert migrated_issue["constraint"] == legacy_issue["constraint"]
        assert migrated_issue.get("flag") == legacy_issue.get("flag")
        assert migrated_issue.get("classification") == legacy_issue.get("classification")
        mz, lz = migrated_issue.get("z_score"), legacy_issue.get("z_score")
        if mz is None or lz is None:
            assert mz == lz
        else:
            assert mz == pytest.approx(lz, abs=1e-9)


def test_constraints_match_legacy_with_a_real_consistent_snr_row():
    row = {"ratio": 2.0}
    estimates = {
        "radius_pc": {"value": 5.0, "error": 0.2},
        "velocity_kms": {"value": 120.0, "error": 5.0},
        "age_yr": {"value": 5.0 * 3.0856775814913673e13 / (120.0 * 1e3) / (365.25 * 86400.0) * 0.4, "error": float("nan")},
    }
    _assert_constraints_match_legacy(row, estimates, min_sigma=4.0)


def test_constraints_match_legacy_with_an_inconsistent_row():
    row = {"ratio": 2.0}
    estimates = {
        "radius_pc": {"value": 5.0, "error": 0.2},
        "velocity_kms": {"value": 120.0, "error": 5.0},
        "age_yr": {"value": 50000.0, "error": 500.0},
        "postshock_temperature_K": {"value": 1.0, "error": 0.1},
    }
    _assert_constraints_match_legacy(row, estimates, min_sigma=4.0)


def test_constraints_match_legacy_with_negative_ratio_measurement_issue():
    row = {"ratio": -1.0}
    _assert_constraints_match_legacy(row, {}, min_sigma=4.0)


def test_constraints_match_legacy_with_empty_estimates():
    _assert_constraints_match_legacy({}, {}, min_sigma=4.0)


@pytest.mark.parametrize("min_sigma", [1.0, 4.0, 8.0])
def test_constraints_match_legacy_across_sigma_thresholds(min_sigma):
    row = {}
    estimates = {
        "radius_pc": {"value": 5.0, "error": 0.2},
        "velocity_kms": {"value": 120.0, "error": 5.0},
        "age_yr": {"value": 4000.0, "error": 50.0},
    }
    _assert_constraints_match_legacy(row, estimates, min_sigma=min_sigma)
