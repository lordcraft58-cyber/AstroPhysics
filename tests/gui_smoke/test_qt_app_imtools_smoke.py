"""Prueba de humo de extremo a extremo de las utilidades de imagen de la
Fase 11.1 (análisis de imagen): recorte por clic, normalización por
percentiles, estadísticas + histograma, y aritmética entre dos imágenes
-- las cuatro capacidades que cierran el bloque "Análisis de imagen" del
Mapa de capacidades IRAF.

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


def _wait_active_worker(qapp, main_window, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


def _wait_dialog_worker(qapp, dialog, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while dialog._worker is not None and dialog._worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


def test_crop_process_via_clicks_creates_smaller_window(qapp, main_window):
    data = np.arange(400, dtype=np.float64).reshape(20, 20)
    sub_window = main_window.add_image_window(data, "crop_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["imtools.crop"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("imtools.crop", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 2.0, 3.0, Qt.MouseButton.LeftButton)
    _click(view, 6.0, 7.0, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert view._picking is False  # dos clics: termina sola (requires_picking=2)

    windows_before = len(main_window.mdi.subWindowList())
    _wait_active_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) >= windows_before  # ya se contó tras el clic; solo confirmamos que no falló
    cropped_window = main_window.mdi.subWindowList()[-1]
    cropped_view = cropped_window.widget()
    assert cropped_view.data.shape == (5, 5)
    np.testing.assert_array_equal(cropped_view.data, data[3:8, 2:7])


def test_normalize_process_runs_end_to_end(qapp, main_window):
    rng = np.random.default_rng(2)
    data = rng.normal(500.0, 20.0, (30, 30))
    sub_window = main_window.add_image_window(data, "normalize_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    process = main_window._process_by_id["imtools.normalize"]
    params = {p.name: p.default for p in process.parameters}
    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("imtools.normalize", params)
    _wait_active_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    new_view = main_window.mdi.subWindowList()[-1].widget()
    assert new_view.data.shape == data.shape


def test_statistics_process_creates_histogram_window_and_reports_values(qapp, main_window):
    data = np.arange(1, 101, dtype=np.float64).reshape(10, 10)
    sub_window = main_window.add_image_window(data, "stats_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    process = main_window._process_by_id["imtools.statistics"]
    params = {p.name: p.default for p in process.parameters}
    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("imtools.statistics", params)
    _wait_active_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    histogram_view = main_window.mdi.subWindowList()[-1].widget()
    assert histogram_view.data.shape[1] == int(params["bins"])


def test_arithmetic_dialog_end_to_end_subtracts_two_open_images(qapp, main_window):
    from qt_app.imtools.arithmetic_dialog import ArithmeticDialog

    data_a = np.full((15, 15), 100.0)
    data_b = np.full((15, 15), 30.0)
    main_window.add_image_window(data_a, "frame_a.fits")
    main_window.add_image_window(data_b, "frame_b.fits")
    qapp.processEvents()

    windows = main_window._image_windows_by_title()
    assert set(windows) == {"frame_a.fits", "frame_b.fits"}

    dialog = ArithmeticDialog(windows, "frame_a.fits", main_window)
    dialog.computed.connect(lambda data, title: main_window.add_image_window(data, title))
    dialog.first_combo.setCurrentText("frame_a.fits")
    dialog.second_combo.setCurrentText("frame_b.fits")
    dialog.operation_combo.setCurrentText("Restar (-)")

    windows_before = len(main_window.mdi.subWindowList())
    dialog._on_apply()
    _wait_dialog_worker(qapp, dialog)

    assert dialog.status_label.text() == ""
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    result_view = main_window.mdi.subWindowList()[-1].widget()
    np.testing.assert_allclose(result_view.data, 70.0)


def test_arithmetic_dialog_rejects_mismatched_shapes(qapp, main_window):
    from qt_app.imtools.arithmetic_dialog import ArithmeticDialog

    main_window.add_image_window(np.full((10, 10), 1.0), "small.fits")
    main_window.add_image_window(np.full((20, 20), 1.0), "big.fits")
    qapp.processEvents()

    windows = main_window._image_windows_by_title()
    dialog = ArithmeticDialog(windows, "small.fits", main_window)
    dialog.first_combo.setCurrentText("small.fits")
    dialog.second_combo.setCurrentText("big.fits")

    dialog._on_apply()

    assert "misma forma" in dialog.status_label.text()
    assert dialog._worker is None  # nunca llegó a lanzar el hilo de fondo


def test_arithmetic_menu_action_warns_with_fewer_than_two_images(qapp, main_window):
    main_window.add_image_window(np.full((5, 5), 1.0), "only_one.fits")
    qapp.processEvents()

    main_window._open_arithmetic_dialog()  # no debe abrir el diálogo ni lanzar excepción

    assert "dos imágenes" in main_window.statusBar().currentMessage()
