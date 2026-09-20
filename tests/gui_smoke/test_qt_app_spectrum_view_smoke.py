"""Prueba de humo del widget `SpectrumView` (visor de espectros 1D real
-- motor 49): mapeo dato<->píxel real, zoom a rueda de ratón, arrastre
para desplazar, doble clic para restablecer la vista, y lectura en vivo
bajo el cursor -- las mismas interacciones reales que ya prueba
`ImageView` en `test_qt_app_picking_smoke.py`, aplicadas al nuevo
widget.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import QPoint, QPointF, Qt  # noqa: E402
from PySide6.QtGui import QMouseEvent, QWheelEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from qt_app.spectroscopy.spectrum_plot_data import SpectrumMarker, SpectrumPlotData, SpectrumSeries  # noqa: E402
from qt_app.spectroscopy.spectrum_view import SpectrumView  # noqa: E402


def _display_available() -> bool:
    try:
        app = QApplication.instance() or QApplication([])
    except Exception:
        return False
    return app is not None


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb) o Qt no puede inicializar")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _linear_plot_data(n=50, x0=6000.0, dx=2.0, amplitude=100.0):
    x = x0 + dx * np.arange(n, dtype=np.float64)
    y = amplitude + 10.0 * np.sin(np.linspace(0, 3, n))
    return SpectrumPlotData(series=(SpectrumSeries(label="Flujo", x=x, y=y),), x_label="Longitud de onda (Å)", y_label="Flujo (ADU)")


def _view(qapp, plot_data=None, size=(400, 300)):
    view = SpectrumView(plot_data or _linear_plot_data(), "prueba.fits")
    view.resize(*size)
    view.show()
    qapp.processEvents()
    return view


def test_data_to_pixel_and_back_round_trips_inside_the_plot_area(qapp):
    view = _view(qapp)
    x_lo, x_hi = view._x_range
    y_lo, y_hi = view._y_range
    x_mid, y_mid = (x_lo + x_hi) / 2.0, (y_lo + y_hi) / 2.0

    pixel = view._data_to_pixel(x_mid, y_mid)
    x_back, y_back = view._pixel_to_data(pixel.x(), pixel.y())

    assert x_back == pytest.approx(x_mid, rel=1e-6)
    assert y_back == pytest.approx(y_mid, rel=1e-6)


def test_reset_view_recovers_the_full_data_range(qapp):
    view = _view(qapp)
    original_x_range = view._x_range
    original_y_range = view._y_range

    view._x_range = (0.0, 1.0)
    view._y_range = (0.0, 1.0)
    view.reset_view()

    assert view._x_range == pytest.approx(original_x_range)
    assert view._y_range == pytest.approx(original_y_range)


def test_wheel_zoom_in_narrows_the_visible_range(qapp):
    view = _view(qapp)
    x_span_before = view._x_range[1] - view._x_range[0]
    y_span_before = view._y_range[1] - view._y_range[0]

    center = view._plot_rect().center()
    event = QWheelEvent(
        QPointF(center), QPointF(center), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(event)

    x_span_after = view._x_range[1] - view._x_range[0]
    y_span_after = view._y_range[1] - view._y_range[0]
    assert x_span_after < x_span_before
    assert y_span_after < y_span_before


def test_wheel_zoom_out_widens_the_visible_range(qapp):
    view = _view(qapp)
    x_span_before = view._x_range[1] - view._x_range[0]

    center = view._plot_rect().center()
    event = QWheelEvent(
        QPointF(center), QPointF(center), QPoint(0, 0), QPoint(0, -120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(event)

    x_span_after = view._x_range[1] - view._x_range[0]
    assert x_span_after > x_span_before


def test_left_drag_pans_the_visible_range(qapp):
    view = _view(qapp)
    x_lo_before, _ = view._x_range

    rect = view._plot_rect()
    start = rect.center()
    end = QPointF(start.x() - 40.0, start.y())

    press = QMouseEvent(QMouseEvent.Type.MouseButtonPress, start, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(press)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, end, Qt.MouseButton.NoButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)
    release = QMouseEvent(QMouseEvent.Type.MouseButtonRelease, end, Qt.MouseButton.LeftButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseReleaseEvent(release)

    x_lo_after, _ = view._x_range
    assert x_lo_after > x_lo_before  # arrastrar hacia la izquierda desplaza la vista hacia longitudes de onda mayores


def test_double_click_resets_the_view_after_zooming(qapp):
    view = _view(qapp)
    original_x_range = view._x_range

    center = view._plot_rect().center()
    wheel = QWheelEvent(
        QPointF(center), QPointF(center), QPoint(0, 0), QPoint(0, 120),
        Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier, Qt.ScrollPhase.NoScrollPhase, False,
    )
    view.wheelEvent(wheel)
    assert view._x_range != original_x_range

    double_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonDblClick, center, Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    view.mouseDoubleClickEvent(double_click)

    assert view._x_range == pytest.approx(original_x_range)


def test_mouse_move_inside_plot_emits_real_data_coordinates(qapp):
    view = _view(qapp)
    received: dict = {}
    view.value_hovered.connect(lambda x, y: received.update(x=x, y=y))

    x_lo, x_hi = view._x_range
    y_lo, y_hi = view._y_range
    expected_x, expected_y = (x_lo + x_hi) / 2.0, (y_lo + y_hi) / 2.0
    pixel = view._data_to_pixel(expected_x, expected_y)

    move = QMouseEvent(QMouseEvent.Type.MouseMove, pixel, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)

    assert received["x"] == pytest.approx(expected_x, rel=1e-3)
    assert received["y"] == pytest.approx(expected_y, rel=1e-3)


def test_mouse_move_outside_plot_area_emits_nan(qapp):
    view = _view(qapp)
    received: dict = {}
    view.value_hovered.connect(lambda x, y: received.update(x=x, y=y))

    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(2.0, 2.0), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)

    assert received["x"] != received["x"]  # NaN


def test_point_hovered_snaps_to_the_nearest_real_data_point_with_error_and_snr(qapp):
    # §29: el tooltip debe reportar el punto REAL más cercano (nunca una
    # lectura interpolada entre dos medidas), con su error real y la S/N
    # derivada de ese error real.
    x = np.array([6000.0, 6002.0, 6004.0, 6006.0])
    y = np.array([100.0, 150.0, 120.0, 90.0])
    y_error = np.array([5.0, 6.0, 4.0, 3.0])
    plot_data = SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo", x=x, y=y, y_error=y_error),),
        x_label="Longitud de onda (Å)", y_label="Flujo (ADU)",
    )
    view = _view(qapp, plot_data)
    received: dict = {}
    view.point_hovered.connect(lambda x, y, y_error, x_label, y_label: received.update(
        x=x, y=y, y_error=y_error, x_label=x_label, y_label=y_label
    ))

    # cursor cerca del segundo punto real (6002.0), pero no exactamente
    # encima -- debe reportar el punto REAL más cercano, no una posición
    # interpolada.
    pixel = view._data_to_pixel(6002.7, 145.0)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, pixel, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)

    assert received["x"] == pytest.approx(6002.0)
    assert received["y"] == pytest.approx(150.0)
    assert received["y_error"] == pytest.approx(6.0)
    assert received["x_label"] == "Longitud de onda (Å)"
    assert received["y_label"] == "Flujo (ADU)"


def test_point_hovered_reports_nan_error_when_the_series_has_no_real_uncertainty(qapp):
    view = _view(qapp)  # _linear_plot_data no lleva y_error
    received: dict = {}
    view.point_hovered.connect(lambda x, y, y_error, x_label, y_label: received.update(y_error=y_error))

    pixel = view._data_to_pixel(6010.0, 100.0)
    move = QMouseEvent(QMouseEvent.Type.MouseMove, pixel, Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)

    assert received["y_error"] != received["y_error"]  # NaN honesto, no un error inventado


def test_point_hovered_emits_all_nan_outside_the_plot_area(qapp):
    view = _view(qapp)
    received: dict = {}
    view.point_hovered.connect(lambda x, y, y_error, x_label, y_label: received.update(x=x, y=y, y_error=y_error))

    move = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(2.0, 2.0), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(move)

    assert received["x"] != received["x"]
    assert received["y"] != received["y"]
    assert received["y_error"] != received["y_error"]


def test_unit_selector_is_absent_for_a_pixel_axis(qapp):
    view = _view(qapp)  # _linear_plot_data no lleva x_unit real
    assert view.unit_combo is None


def test_unit_selector_appears_and_converts_the_real_x_axis(qapp):
    plot_data = SpectrumPlotData(
        series=(SpectrumSeries(label="Flujo", x=np.array([6000.0, 6500.0]), y=np.array([100.0, 120.0])),),
        x_label="Longitud de onda (Å)", y_label="Flujo (ADU)", x_unit="Å",
    )
    view = _view(qapp, plot_data)
    assert view.unit_combo is not None
    assert view.unit_combo.currentText() == "Å"
    assert view._data.series[0].x[0] == pytest.approx(6000.0)

    view.unit_combo.setCurrentText("nm")

    assert view._data.x_unit == "nm"
    assert view._data.series[0].x[0] == pytest.approx(600.0)
    assert view._data.x_label == "Longitud de onda (nm)"


def test_series_with_nan_gap_builds_a_broken_path_without_crashing(qapp):
    x = np.array([0.0, 1.0, 2.0, 3.0, 4.0])
    y = np.array([1.0, 2.0, np.nan, 4.0, 5.0])
    plot_data = SpectrumPlotData(series=(SpectrumSeries(label="Con hueco", x=x, y=y),), x_label="X", y_label="Y")
    view = _view(qapp, plot_data)

    view.repaint()  # no debe lanzar ninguna excepción con un hueco real en los datos
    qapp.processEvents()


def test_plot_data_with_marker_and_legend_renders_without_crashing(qapp):
    x = np.linspace(6000.0, 6100.0, 40)
    plot_data = SpectrumPlotData(
        series=(
            SpectrumSeries(label="Flujo", x=x, y=np.full_like(x, 100.0)),
            SpectrumSeries(label="Continuo", x=x, y=np.full_like(x, 95.0), style="dashed", color="#d9a441"),
        ),
        x_label="Longitud de onda (Å)", y_label="Flujo (ADU)",
        markers=(SpectrumMarker(x_start=6020.0, x_end=6040.0, label="Ventana"),),
    )
    view = _view(qapp, plot_data)
    view.repaint()
    qapp.processEvents()
