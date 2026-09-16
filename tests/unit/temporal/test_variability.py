from __future__ import annotations

from astrophysics_suite.temporal.variability import analyze_variability


def test_constant_source_is_not_variable():
    epochs = [{"time": t, "value": 10.0, "error": 0.05} for t in range(5)]
    result = analyze_variability(epochs, detection_id="DET-0001")
    assert result.n_epochs == 5
    assert result.variable_candidate is False


def test_clear_linear_trend_is_flagged_variable():
    epochs = [{"time": t, "value": 10.0 + 1.0 * t, "error": 0.05} for t in range(6)]
    result = analyze_variability(epochs, detection_id="DET-0002")
    assert result.variable_candidate is True
    assert result.brightness_change is not None
    assert result.brightness_change.value > 0


def test_insufficient_epochs_reports_not_active_with_reason():
    epochs = [{"time": 0, "value": 1.0, "error": 0.1}]
    result = analyze_variability(epochs, detection_id="DET-0003", min_epochs=3)
    assert result.n_epochs == 1  # se parseó 1 punto válido, pero es menos que min_epochs=3
    assert result.variable_candidate is False
    assert result.notes


def test_roundtrip():
    from astrophysics_suite.models.temporal import TemporalEvidence

    epochs = [{"time": t, "value": 10.0 + 0.5 * t, "error": 0.05} for t in range(4)]
    result = analyze_variability(epochs, detection_id="DET-0004")
    assert TemporalEvidence.from_dict(result.to_dict()) == result
