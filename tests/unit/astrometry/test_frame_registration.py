from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.astrometry.frame_registration import estimate_frame_translation, refine_position


def _field(n=25, seed=0):
    rng = np.random.default_rng(seed)
    return rng.uniform(0, 1000, size=(n, 2))


def test_recovers_a_known_translation():
    reference = _field()
    dx_true, dy_true = 12.3, -7.8
    target = reference + np.array([dx_true, dy_true])
    dx, dy, score = estimate_frame_translation(reference, target)
    assert dx == pytest.approx(dx_true, abs=0.5)
    assert dy == pytest.approx(dy_true, abs=0.5)
    assert score == len(reference)


def test_recovers_translation_with_partial_field_overlap():
    reference = _field(n=30)
    dx_true, dy_true = -20.0, 15.0
    target = reference[:20] + np.array([dx_true, dy_true])  # solo 20 de 30 sobreviven (borde del campo)
    dx, dy, score = estimate_frame_translation(reference, target)
    assert dx == pytest.approx(dx_true, abs=0.5)
    assert dy == pytest.approx(dy_true, abs=0.5)
    assert score >= 18


def test_zero_translation_for_identical_fields():
    reference = _field()
    dx, dy, score = estimate_frame_translation(reference, reference.copy())
    assert dx == pytest.approx(0.0, abs=1e-6)
    assert dy == pytest.approx(0.0, abs=1e-6)
    assert score == len(reference)


def test_empty_lists_return_no_translation_honestly():
    dx, dy, score = estimate_frame_translation(np.empty((0, 2)), _field())
    assert (dx, dy, score) == (0.0, 0.0, 0)
    dx, dy, score = estimate_frame_translation(_field(), np.empty((0, 2)))
    assert (dx, dy, score) == (0.0, 0.0, 0)


def test_low_score_when_fields_share_no_real_pattern():
    reference = _field(seed=1)
    unrelated = _field(seed=2)
    _dx, _dy, score = estimate_frame_translation(reference, unrelated)
    # un patrón aleatorio no relacionado no debe alinear casi nada del campo real
    assert score < len(reference) // 3


def test_refine_position_snaps_to_the_nearest_real_source():
    detected = np.array([[100.0, 100.0], [500.0, 500.0]])
    x, y, refined = refine_position(detected, 101.5, 98.7, search_radius_px=4.0)
    assert refined is True
    assert (x, y) == (100.0, 100.0)


def test_refine_position_keeps_prediction_when_nothing_real_is_close():
    detected = np.array([[500.0, 500.0]])
    x, y, refined = refine_position(detected, 10.0, 10.0, search_radius_px=4.0)
    assert refined is False
    assert (x, y) == (10.0, 10.0)


def test_refine_position_with_no_detections_keeps_prediction():
    x, y, refined = refine_position(np.empty((0, 2)), 10.0, 20.0)
    assert refined is False
    assert (x, y) == (10.0, 20.0)
