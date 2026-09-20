"""Prueba de humo de extremo a extremo del overlay de traza/apertura/
cielo sobre la imagen 2D real (hueco más repetido del encargo de 43
secciones -- §2, §3, §5, §28: hasta ahora, trazar/extraer un espectro
era una caja negra, sin ver nunca sobre la imagen qué traza/apertura/
cielo se usó de verdad).

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import Qt, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402


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


@pytest.fixture
def main_window(qapp):
    from qt_app.main_window import MainWindow

    window = MainWindow()
    window.show()
    qapp.processEvents()
    yield window
    window.close()


def _click(view, scene_x: float, scene_y: float, button: Qt.MouseButton) -> None:
    view_point = view.mapFromScene(QPointF(scene_x, scene_y))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(view_point), button, button, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(event)


def _wait_active_worker(qapp, main_window, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def test_image_view_set_and_clear_trace_overlay_adds_and_removes_scene_items():
    from qt_app.mdi.image_window import ImageView
    from qt_app.spectroscopy.trace_overlay_data import TraceOverlay
    from astrophysics_suite.spectroscopy.trace import SkyWindow

    data = np.full((40, 100), 100.0)
    view = ImageView(data, "overlay_direct_test.fits")

    items_before = len(view._scene.items())
    overlay = TraceOverlay(
        trace_columns=np.arange(100, dtype=np.float64), trace_center_px=np.full(100, 20.0),
        aperture_half_width=4.0, sky_windows=(SkyWindow(offset_px=-10.0, half_width_px=4.0),), label="Traza",
    )
    view.set_trace_overlay(overlay)
    # traza (1) + 2 límites de apertura + 2 líneas de la única ventana de cielo = 5 items nuevos
    assert len(view._scene.items()) == items_before + 5
    assert len(view._trace_overlay_items) == 5

    view.clear_trace_overlay()
    assert len(view._scene.items()) == items_before
    assert view._trace_overlay_items == []


def test_image_view_set_trace_overlay_accepts_a_tuple_of_overlays():
    from qt_app.mdi.image_window import ImageView
    from qt_app.spectroscopy.trace_overlay_data import TraceOverlay

    data = np.full((40, 100), 100.0)
    view = ImageView(data, "overlay_multi_test.fits")

    overlays = (
        TraceOverlay(trace_columns=np.arange(100, dtype=np.float64), trace_center_px=np.full(100, 10.0), aperture_half_width=3.0, label="A"),
        TraceOverlay(trace_columns=np.arange(100, dtype=np.float64), trace_center_px=np.full(100, 30.0), aperture_half_width=3.0, label="B"),
    )
    view.set_trace_overlay(overlays)
    # cada overlay sin cielo: traza + 2 límites = 3 items -> 6 en total
    assert len(view._trace_overlay_items) == 6


def test_spectral_trace_process_draws_a_real_overlay_on_the_2d_image(qapp, main_window):
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile
    sub_window = main_window.add_image_window(data, "overlay_trace.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view._trace_overlay_items == []

    process = main_window._process_by_id["spectroscopy.trace"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.trace", params)
    qapp.processEvents()
    _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    _wait_active_worker(qapp, main_window)

    assert len(view._trace_overlay_items) > 0
