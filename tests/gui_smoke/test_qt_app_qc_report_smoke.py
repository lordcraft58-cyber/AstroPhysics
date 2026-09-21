"""Prueba de humo de extremo a extremo del informe de control de calidad
unificado (§31): un único clic reutiliza la misma traza/extracción real
que 'Extracción de traza' y reporta un semáforo OK/WARNING/ERROR por
métrica -- sin abrir ninguna ventana nueva (es un informe, no un
espectro ni una imagen nueva).

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


def test_qc_report_process_runs_end_to_end_via_click_without_opening_a_new_window(qapp, main_window):
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 6000.0 * profile
    sub_window = main_window.add_image_window(data, "qc_report.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    windows_before = len(main_window.mdi.subWindowList())

    process = main_window._process_by_id["spectroscopy.qc_report"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.qc_report", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    _wait_active_worker(qapp, main_window)

    # informe puro (summary/log/table) -- no abre ninguna ventana nueva
    assert len(main_window.mdi.subWindowList()) == windows_before
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 6
    metric_names = [row[0] for row in main_window._last_result_table.rows]
    assert metric_names == [
        "Traza espacial", "Calibración en longitud de onda", "Rango de longitud de onda", "Dispersión (centro)",
        "Relación señal/ruido", "Calidad de píxeles",
    ]
