"""Prueba de humo de extremo a extremo de la edición interactiva de la
apertura sobre el overlay de traza real (§2): arrastrar el borde real
de la apertura recalcula la extracción con la MISMA traza ya conocida
(sin retrazar, sin pedir un nuevo clic), y "bloquear" desactiva
realmente el arrastre.

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
    event = QMouseEvent(QMouseEvent.Type.MouseButtonPress, QPointF(view_point), button, button, Qt.KeyboardModifier.NoModifier)
    view.mousePressEvent(event)


def _mouse_event(view, event_type, scene_x: float, scene_y: float, *, button, buttons) -> QMouseEvent:
    view_point = view.mapFromScene(QPointF(scene_x, scene_y))
    return QMouseEvent(event_type, QPointF(view_point), button, buttons, Qt.KeyboardModifier.NoModifier)


def _press(view, x: float, y: float) -> None:
    view.mousePressEvent(_mouse_event(view, QMouseEvent.Type.MouseButtonPress, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.LeftButton))


def _drag_move(view, x: float, y: float) -> None:
    view.mouseMoveEvent(_mouse_event(view, QMouseEvent.Type.MouseMove, x, y, button=Qt.MouseButton.NoButton, buttons=Qt.MouseButton.LeftButton))


def _release(view, x: float, y: float) -> None:
    view.mouseReleaseEvent(_mouse_event(view, QMouseEvent.Type.MouseButtonRelease, x, y, button=Qt.MouseButton.LeftButton, buttons=Qt.MouseButton.NoButton))


def _wait_active_worker(qapp, main_window, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def _traced_view(qapp, main_window, *, title="aperture_edit.fits"):
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile  # sin ruido: el centro real cae exactamente en y=20.0 en toda columna
    sub_window = main_window.add_image_window(data, title)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["spectroscopy.trace"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.trace", params)
    qapp.processEvents()
    _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    _wait_active_worker(qapp, main_window)
    assert view.trace_edit_context is not None
    return view, params["aperture_half_width"]


def test_dragging_the_aperture_edge_recalculates_the_extraction_without_reclicking(qapp, main_window):
    view, default_half_width = _traced_view(qapp, main_window)
    windows_before = len(main_window.mdi.subWindowList())
    history_before = len(view.processing_history)

    top_edge_y = 20.0 - default_half_width
    _press(view, 75.0, top_edge_y)
    assert view._dragging_aperture is True

    new_edge_y = 10.0  # semiancho real = |10 - 20| = 10.0
    _drag_move(view, 75.0, new_edge_y)
    qapp.processEvents()
    assert view._live_aperture_half_width == pytest.approx(10.0, abs=0.6)

    _release(view, 75.0, new_edge_y)
    qapp.processEvents()

    assert view._dragging_aperture is False
    assert view._trace_overlay_single.aperture_half_width == pytest.approx(10.0, abs=0.6)
    # se abrió una ventana de espectro nueva con el resultado recalculado real, sin ningún clic nuevo
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    assert len(view.processing_history) == history_before + 1
    assert "Recalcular" in view.processing_history[-1].process_name


def test_locking_the_view_prevents_dragging_the_aperture(qapp, main_window):
    view, default_half_width = _traced_view(qapp, main_window, title="aperture_locked.fits")
    view.trace_overlay_locked = True

    top_edge_y = 20.0 - default_half_width
    _press(view, 75.0, top_edge_y)
    assert view._dragging_aperture is False  # bloqueado: el clic no entra en modo arrastre


def test_clicking_far_from_the_aperture_edge_does_not_start_a_drag(qapp, main_window):
    view, _default_half_width = _traced_view(qapp, main_window, title="aperture_far_click.fits")

    _press(view, 75.0, 20.0)  # justo en el CENTRO de la traza, lejos de cualquier borde real
    assert view._dragging_aperture is False
