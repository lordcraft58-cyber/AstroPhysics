"""Prueba de humo de extremo a extremo del mapa de calidad de píxeles
(menú de procesos -> Espectroscopía -> "Mapa de calidad de píxeles..."):
confirma que abre una ventana nueva con los píxeles reales marcados
(NaN/Inf siempre, saturados si la cabecera trae SATURATE real, rayos
cósmicos solo si se activa la detección) -- mismos umbrales/motor que ya
usan spectroscopy.trace/multiaperture/extended_extraction (slices 12/13),
aquí visibles píxel a píxel.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import time

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

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


def _wait_active_worker(qapp, main_window, timeout_s=5.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()


def test_quality_map_process_opens_a_window_with_real_saturated_pixels_marked(qapp, main_window):
    data = np.full((20, 20), 100.0)
    data[5, 5] = 900.0
    data[10, 10] = np.nan

    sub_window = main_window.add_image_window(data, "quality_map_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    sub_window.widget().header = {"SATURATE": 800.0}
    qapp.processEvents()

    process = main_window._process_by_id["spectroscopy.quality_map"]
    params = {p.name: p.default for p in process.parameters}
    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("spectroscopy.quality_map", params)
    _wait_active_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    quality_view = main_window.mdi.subWindowList()[-1].widget()
    assert quality_view.data.shape == data.shape
    assert quality_view.data[5, 5] != 0.0
    assert quality_view.data[10, 10] != 0.0
    assert quality_view.data[0, 0] == 0.0
    assert np.count_nonzero(quality_view.data) == 2


def test_quality_map_process_requires_no_picking(qapp, main_window):
    data = np.full((10, 10), 50.0)
    sub_window = main_window.add_image_window(data, "quality_map_nopick.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["spectroscopy.quality_map"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.quality_map", params)
    qapp.processEvents()

    assert view._picking is False  # va directo al hilo de fondo, sin picking
