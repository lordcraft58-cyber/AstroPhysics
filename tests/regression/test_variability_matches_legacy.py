"""`temporal/variability.py::_analyze_temporal_change` +
`_weighted_linear_fit` (migrados del monolito legacy en el cierre
sistemático del motor 9/16, informe 97) deben producir EXACTAMENTE lo
mismo que `legacy.TemporalChangeEngine.analyze` -- campo a campo,
reimplementación 1:1 sin ningún cambio deliberado de fórmula.
"""
from __future__ import annotations

import pytest

from astrophysics_suite.temporal.variability import _analyze_temporal_change
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import TemporalChangeEngine as _LegacyTemporalChangeEngine

_SCALAR_FIELDS = ("state", "n_epochs", "weighted_mean", "constant_chi2", "constant_reduced_chi2", "slope_sigma", "variable_candidate", "threshold_sigma")
_LINEAR_FIT_FIELDS = ("intercept", "slope", "intercept_err", "slope_err", "chi2", "reduced_chi2", "n")


def _assert_matches_legacy(epochs, **kwargs):
    migrated = _analyze_temporal_change(epochs, **kwargs)
    legacy = _LegacyTemporalChangeEngine().analyze(epochs, **kwargs)

    assert migrated["state"] == legacy["state"]
    assert migrated["n_epochs"] == legacy["n_epochs"]

    if migrated["state"] != "ACTIVE":
        assert migrated.get("reason") == legacy.get("reason")
        return

    for field in _SCALAR_FIELDS:
        expected_m, expected_l = migrated[field], legacy[field]
        if isinstance(expected_m, float) and isinstance(expected_l, float):
            assert expected_m == pytest.approx(expected_l, abs=1e-9), f"{field}: {expected_m} != {expected_l}"
        else:
            assert expected_m == expected_l, f"{field}: {expected_m} != {expected_l}"

    for field in _LINEAR_FIT_FIELDS:
        expected_m, expected_l = migrated["linear_fit"][field], legacy["linear_fit"][field]
        assert expected_m == pytest.approx(expected_l, abs=1e-9), f"linear_fit.{field}: {expected_m} != {expected_l}"


def test_matches_legacy_on_a_clear_linear_trend():
    epochs = [{"time": t, "value": 10.0 + 1.0 * t, "error": 0.05} for t in range(6)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_on_a_constant_source():
    epochs = [{"time": t, "value": 10.0, "error": 0.05} for t in range(5)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_with_noisy_realistic_data():
    values = [10.02, 10.05, 9.98, 10.12, 10.20, 10.08, 10.31, 10.15]
    epochs = [{"time": float(t), "value": v, "error": 0.06} for t, v in enumerate(values)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_when_insufficient_epochs():
    epochs = [{"time": 0, "value": 1.0, "error": 0.1}]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_with_epoch_alias_keys():
    epochs = [{"epoch": t, "value": 10.0 + 0.3 * t, "sigma": 0.07} for t in range(5)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_dropping_malformed_and_zero_error_points():
    epochs = [{"time": t, "value": 10.0 + 0.2 * t, "error": 0.05} for t in range(5)]
    epochs.append({"time": 99, "value": 10.0, "error": 0.0})
    epochs.append("not a dict")
    epochs.append({"time": "nope", "value": 1.0, "error": 0.1})
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=4.0)


def test_matches_legacy_with_high_chi2_triggering_variable_via_constant_fit():
    # Alternando muy por encima/por debajo del error, sin tendencia neta:
    # dispara variable_candidate por chi2 constante alto, no por pendiente.
    values = [10.0, 10.6, 9.4, 10.6, 9.4, 10.6, 9.4, 10.6]
    epochs = [{"time": float(t), "value": v, "error": 0.05} for t, v in enumerate(values)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=100.0)


@pytest.mark.parametrize("sigma_threshold", [1.0, 4.0, 10.0])
def test_matches_legacy_across_sigma_thresholds(sigma_threshold):
    epochs = [{"time": t, "value": 10.0 + 0.4 * t, "error": 0.08} for t in range(7)]
    _assert_matches_legacy(epochs, min_epochs=3, sigma_threshold=sigma_threshold)


def test_weighted_linear_fit_matches_legacy_directly():
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _weighted_linear_fit as _legacy_fit

    from astrophysics_suite.temporal.variability import _weighted_linear_fit as _migrated_fit

    import numpy as np

    rng = np.random.default_rng(42)
    x = np.linspace(0, 10, 12)
    y = 3.0 + 2.5 * x + rng.normal(0, 0.3, size=x.size)
    sigma = np.full_like(x, 0.3)

    migrated = _migrated_fit(x, y, sigma)
    legacy = _legacy_fit(x, y, sigma)
    for field in _LINEAR_FIT_FIELDS:
        assert migrated[field] == pytest.approx(legacy[field], abs=1e-9), f"{field}: {migrated[field]} != {legacy[field]}"


def test_weighted_linear_fit_raises_with_fewer_than_two_points_like_legacy():
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _weighted_linear_fit as _legacy_fit

    from astrophysics_suite.temporal.variability import _weighted_linear_fit as _migrated_fit

    with pytest.raises(ValueError):
        _migrated_fit([1.0], [1.0], [0.1])
    with pytest.raises(ValueError):
        _legacy_fit([1.0], [1.0], [0.1])
