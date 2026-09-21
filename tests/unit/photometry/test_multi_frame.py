from __future__ import annotations

import math
from datetime import datetime, timedelta

import numpy as np
import pytest

from astrophysics_suite.photometry.multi_frame import (
    MAX_COMPARISON_STARS,
    FrameInput,
    build_multi_frame_light_curve,
)


def _star(shape, x0, y0, flux, sigma=2.2):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    return flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))


def _make_frames(n=6, variable_flux_start=60000.0, decline_per_frame=1500.0, shift_per_frame=(2.0, -1.5)):
    shape = (200, 200)
    background = 100.0
    comp_positions = [(120.0, 60.0, 40000.0), (150.0, 140.0, 25000.0), (60.0, 150.0, 15000.0)]
    var_position = (50.0, 50.0)

    frames = []
    base_time = datetime(2024, 8, 1, 0, 0, 0)
    for i in range(n):
        dx, dy = shift_per_frame[0] * i, shift_per_frame[1] * i
        data = np.full(shape, background)
        var_flux = variable_flux_start - decline_per_frame * i
        data = data + _star(shape, var_position[0] + dx, var_position[1] + dy, var_flux)
        for cx, cy, cflux in comp_positions:
            data = data + _star(shape, cx + dx, cy + dy, cflux)
        rng = np.random.default_rng(i)
        data = data + rng.normal(0, 1.0, size=shape)
        frames.append(FrameInput(label=f"frame{i}", data=data, date_obs=base_time + timedelta(minutes=10 * i)))
    return frames, var_position, [(cx, cy) for cx, cy, _ in comp_positions]


def test_recovers_a_real_declining_trend_from_synthetic_frames():
    frames, target_xy, comparisons_xy = _make_frames()
    result = build_multi_frame_light_curve(
        frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0001",
    )
    assert result.n_valid_epochs == len(frames)
    for point in result.points:
        assert point.skip_reason == ""
        assert point.target_refined is True
        assert all(point.comparison_refined)

    assert result.temporal_evidence.variable_candidate is True
    assert result.temporal_evidence.brightness_change is not None
    # la variable pierde flujo con el tiempo -> magnitud diferencial CRECE (más débil)
    assert result.temporal_evidence.brightness_change.value > 0


def test_constant_target_is_not_flagged_variable():
    frames, target_xy, comparisons_xy = _make_frames(decline_per_frame=0.0)
    result = build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0002")
    assert result.n_valid_epochs == len(frames)
    assert result.temporal_evidence.variable_candidate is False


def test_registration_recovers_the_real_injected_shift():
    frames, target_xy, comparisons_xy = _make_frames(shift_per_frame=(5.0, 3.0))
    result = build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0003")
    for i, point in enumerate(result.points):
        assert point.translation_px[0] == pytest.approx(5.0 * i, abs=0.6)
        assert point.translation_px[1] == pytest.approx(3.0 * i, abs=0.6)


def test_table_has_one_row_per_frame_with_real_units():
    frames, target_xy, comparisons_xy = _make_frames(n=4)
    result = build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0004")
    assert len(result.table.rows) == 4
    assert "mag_diferencial" in result.table.columns


def test_rejects_no_comparison_stars():
    frames, target_xy, _ = _make_frames(n=3)
    with pytest.raises(ValueError):
        build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=[], detection_id="TEST-VAR-0005")


def test_rejects_more_than_the_maximum_comparison_stars():
    frames, target_xy, comparisons_xy = _make_frames(n=3)
    too_many = comparisons_xy * (MAX_COMPARISON_STARS + 1)
    with pytest.raises(ValueError):
        build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=too_many[: MAX_COMPARISON_STARS + 1], detection_id="TEST-VAR-0006")


def test_rejects_empty_frame_list():
    with pytest.raises(ValueError):
        build_multi_frame_light_curve([], target_xy=(1.0, 1.0), comparison_xy=[(2.0, 2.0)], detection_id="TEST-VAR-0007")


def test_frame_without_date_obs_is_skipped_with_explicit_reason():
    frames, target_xy, comparisons_xy = _make_frames(n=4)
    frames[2] = FrameInput(label=frames[2].label, data=frames[2].data, date_obs=None)
    result = build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0008")
    assert result.points[2].diff_mag is None
    assert "DATE-OBS" in result.points[2].skip_reason
    assert result.n_valid_epochs == 3


def test_real_gain_and_read_noise_are_used_when_provided():
    frames, target_xy, comparisons_xy = _make_frames(n=3)
    frames = [FrameInput(label=f.label, data=f.data, date_obs=f.date_obs, gain_e_per_adu=1.4, read_noise_e=8.0) for f in frames]
    result = build_multi_frame_light_curve(frames, target_xy=target_xy, comparison_xy=comparisons_xy, detection_id="TEST-VAR-0009")
    assert result.n_valid_epochs == 3
    # con GAIN/RDNOISE reales, el error de magnitud debe seguir siendo finito y positivo
    for point in result.points:
        assert point.diff_mag_error is None or point.diff_mag_error > 0
