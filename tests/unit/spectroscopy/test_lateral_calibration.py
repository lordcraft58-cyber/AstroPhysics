"""`lateral_calibration.py`: extracción de una lámpara de calibración
lateral/simultánea (§14/§45) -- sigue la traza del objeto desplazada,
sin sustracción de cielo, y nunca rellena con cero una columna sin
evidencia usable."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.lateral_calibration import (
    LateralCalibrationWindow,
    extract_lateral_calibration_spectrum,
)
from astrophysics_suite.spectroscopy.trace import TraceResult


def _flat_trace(n_columns=200, center=20.0, curve=0.0):
    columns = np.arange(n_columns)
    center_px = center + curve * (columns / n_columns) ** 2
    return TraceResult(columns=columns, center_px=center_px, fit_degree=1, rms_residual_px=0.0, n_columns_used_for_fit=n_columns)


def _frame_with_lateral_lamp(shape=(41, 200), *, object_center=20.0, lamp_offset=12.0, lamp_level=500.0, background=50.0, seed=2):
    rng = np.random.default_rng(seed)
    height, width = shape
    data = np.full(shape, background) + rng.normal(0, 2.0, shape)
    lamp_row = int(round(object_center + lamp_offset))
    data[lamp_row - 2 : lamp_row + 3, :] += lamp_level
    # también hay señal del objeto real, para comprobar que la ventana
    # lateral no la mezcla con la de la lámpara
    obj_row = int(round(object_center))
    data[obj_row - 2 : obj_row + 3, :] += 3000.0
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data, uncertainty


def test_extracts_the_lamp_signal_not_the_object_signal():
    data, uncertainty = _frame_with_lateral_lamp()
    trace = _flat_trace()
    window = LateralCalibrationWindow(offset_px=12.0, half_width_px=2.0)

    result = extract_lateral_calibration_spectrum(data, trace, window, uncertainty=uncertainty)

    assert np.all(result.valid)
    median_flux = float(np.median(result.flux))
    # la ventana cubre 5 filas a nivel lamp_level (500) sobre fondo (50):
    # suma nominal ~= 5*(500+50) = 2750, muy por debajo de la señal del
    # objeto (~5*3050=15250) -- si se mezclaran ambas señales, este valor
    # sería mucho mayor.
    assert 2000.0 < median_flux < 3500.0


def test_follows_the_trace_curvature_like_a_sky_window():
    data, uncertainty = _frame_with_lateral_lamp(object_center=20.0, lamp_offset=10.0)
    trace = _flat_trace(center=20.0, curve=5.0)  # traza curvada, la lámpara la sigue igual
    window = LateralCalibrationWindow(offset_px=10.0, half_width_px=2.0)

    result = extract_lateral_calibration_spectrum(data, trace, window, uncertainty=uncertainty)
    assert np.count_nonzero(result.valid) > 0.9 * data.shape[1]


def test_window_off_the_image_edge_is_invalid_not_zero():
    data, uncertainty = _frame_with_lateral_lamp(shape=(41, 200), object_center=20.0)
    trace = _flat_trace(center=20.0)
    window = LateralCalibrationWindow(offset_px=100.0, half_width_px=2.0)  # muy fuera de la imagen

    result = extract_lateral_calibration_spectrum(data, trace, window, uncertainty=uncertainty)
    assert not np.any(result.valid)
    assert np.all(np.isnan(result.flux))


def test_fully_masked_calibration_window_is_invalid_not_zero():
    data, uncertainty = _frame_with_lateral_lamp()
    trace = _flat_trace()
    window = LateralCalibrationWindow(offset_px=12.0, half_width_px=2.0)

    lamp_row = 32  # object_center(20) + lamp_offset(12)
    mask = np.zeros(data.shape, dtype=bool)
    mask[lamp_row - 2 : lamp_row + 3, :] = True

    result = extract_lateral_calibration_spectrum(data, trace, window, uncertainty=uncertainty, mask=mask)
    assert not np.any(result.valid)
    assert np.all(np.isnan(result.flux))


def test_without_uncertainty_flux_uncertainty_is_nan_not_fabricated():
    data, _ = _frame_with_lateral_lamp()
    trace = _flat_trace()
    window = LateralCalibrationWindow(offset_px=12.0, half_width_px=2.0)

    result = extract_lateral_calibration_spectrum(data, trace, window)
    assert np.all(result.valid)
    assert np.all(np.isnan(result.flux_uncertainty))


def test_uncertainty_shape_mismatch_raises():
    data, _ = _frame_with_lateral_lamp()
    trace = _flat_trace()
    window = LateralCalibrationWindow(offset_px=12.0, half_width_px=2.0)

    with pytest.raises(ValueError):
        extract_lateral_calibration_spectrum(data, trace, window, uncertainty=np.zeros((3, 3)))


def test_method_is_labeled_lateral_calibration():
    data, uncertainty = _frame_with_lateral_lamp()
    trace = _flat_trace()
    window = LateralCalibrationWindow(offset_px=12.0, half_width_px=2.0)

    result = extract_lateral_calibration_spectrum(data, trace, window, uncertainty=uncertainty)
    assert result.method == "lateral_calibration"
    assert result.sky is None
