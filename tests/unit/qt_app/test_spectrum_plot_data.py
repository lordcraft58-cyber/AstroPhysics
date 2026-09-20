"""`spectrum_plot_data.py`: contrato puro (sin PySide6) del visor de
espectros -- `convert_wavelength_plot_data` es conversión de unidades
real (§15), nunca una física distinta."""
from __future__ import annotations

import numpy as np
import pytest

from qt_app.spectroscopy.spectrum_plot_data import (
    SpectrumMarker,
    SpectrumPlotData,
    SpectrumSeries,
    convert_wavelength_plot_data,
)


def _wavelength_plot_data() -> SpectrumPlotData:
    x = np.array([6000.0, 6500.0, 7000.0])
    y = np.array([100.0, 150.0, 120.0])
    y_error = np.array([5.0, 6.0, 4.0])
    return SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo", x=x, y=y, y_error=y_error),),
        x_label="Longitud de onda (Å)", y_label="Flujo (ADU)",
        markers=(SpectrumMarker(x_start=6480.0, x_end=6520.0, label="línea"),),
        x_unit="Å",
    )


def test_convert_angstrom_to_nm_divides_by_ten():
    converted = convert_wavelength_plot_data(_wavelength_plot_data(), "nm")
    assert converted.x_unit == "nm"
    assert converted.x_label == "Longitud de onda (nm)"
    np.testing.assert_allclose(converted.series[0].x, [600.0, 650.0, 700.0])
    # y y_error NUNCA se tocan -- son flujo/incertidumbre real, no longitud de onda
    np.testing.assert_allclose(converted.series[0].y, [100.0, 150.0, 120.0])
    np.testing.assert_allclose(converted.series[0].y_error, [5.0, 6.0, 4.0])
    assert converted.markers[0].x_start == pytest.approx(648.0)
    assert converted.markers[0].x_end == pytest.approx(652.0)


def test_convert_angstrom_to_micron():
    converted = convert_wavelength_plot_data(_wavelength_plot_data(), "μm")
    np.testing.assert_allclose(converted.series[0].x, [0.6, 0.65, 0.7])


def test_convert_round_trip_is_the_identity():
    original = _wavelength_plot_data()
    round_trip = convert_wavelength_plot_data(convert_wavelength_plot_data(original, "nm"), "Å")
    np.testing.assert_allclose(round_trip.series[0].x, original.series[0].x)


def test_convert_to_the_same_unit_is_a_no_op():
    original = _wavelength_plot_data()
    assert convert_wavelength_plot_data(original, "Å") is original


def test_convert_rejects_a_plot_without_a_real_wavelength_unit():
    pixel_plot = SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo", x=np.arange(10.0), y=np.arange(10.0)),),
        x_label="Píxel (dispersión)", y_label="Flujo (ADU)",
    )
    with pytest.raises(ValueError):
        convert_wavelength_plot_data(pixel_plot, "nm")


def test_convert_rejects_an_unknown_target_unit():
    with pytest.raises(ValueError):
        convert_wavelength_plot_data(_wavelength_plot_data(), "cm")
