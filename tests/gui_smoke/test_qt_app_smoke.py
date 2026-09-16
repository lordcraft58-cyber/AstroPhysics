"""Prueba de humo del taller PixInsight/Qt (Fase 9.6): la ventana debe
construirse, cargar una imagen, y ejecutar un proceso real de principio
a fin (incluido el hilo de fondo) sin excepción -- el mismo nivel de
exigencia que `tests/gui_smoke/test_app_smoke.py` aplicó a la GUI en
Tkinter de la Fase 8.

Requiere PySide6 y un display X (real o Xvfb) -- si no están disponibles,
el test se salta en vez de fallar por una razón ajena al código bajo
prueba.
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
    yield window
    window.close()


def _synthetic_field(shape=(80, 80), seed=0):
    rng = np.random.default_rng(seed)
    data = 200.0 + rng.normal(0, 8.0, shape)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    data += 8000.0 / (2 * np.pi * 3.0**2) * np.exp(-(((xx - 40) ** 2 + (yy - 40) ** 2)) / (2 * 3.0**2))
    data[10, 60] += 20000.0  # rayo cósmico inyectado
    return data


def _run_process_and_wait(qapp, main_window, process_id: str, params: dict, timeout_s: float = 5.0):
    process = main_window._process_by_id[process_id]
    main_window._run_process(process_id, params)
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    return process


def test_main_window_builds_without_exception(main_window):
    assert main_window.windowTitle().startswith("AstroPhysics Suite")
    assert main_window.mdi is not None
    assert len(main_window._processes) > 0


def test_process_explorer_lists_both_wired_and_unwired_processes(main_window):
    wired = [p for p in main_window._processes if p.is_wired]
    unwired = [p for p in main_window._processes if not p.is_wired]
    assert wired and unwired


def test_add_image_window_creates_mdi_subwindow(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "test.fits")
    qapp.processEvents()
    assert sub_window in main_window.mdi.subWindowList()
    assert sub_window.widget().data is data


def test_running_cosmic_ray_process_creates_cleaned_output_window(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "cr_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    windows_before = len(main_window.mdi.subWindowList())
    default_params = {p.name: p.default for p in main_window._process_by_id["imtools.cosmic_rays"].parameters}
    _run_process_and_wait(qapp, main_window, "imtools.cosmic_rays", default_params)

    windows_after = main_window.mdi.subWindowList()
    assert len(windows_after) == windows_before + 1
    new_view = windows_after[-1].widget()
    assert abs(new_view.data[10, 60] - 200.0) < 100.0  # el pico inyectado debe haberse limpiado


def test_running_measurement_process_does_not_create_new_window(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "phot_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    windows_before = len(main_window.mdi.subWindowList())
    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.aperture"].parameters}
    _run_process_and_wait(qapp, main_window, "photometry.aperture", default_params)

    assert len(main_window.mdi.subWindowList()) == windows_before


def test_running_process_without_active_image_reports_status_and_does_not_crash(qapp, main_window):
    for sub_window in list(main_window.mdi.subWindowList()):
        sub_window.close()
    qapp.processEvents()

    default_params = {p.name: p.default for p in main_window._process_by_id["imtools.cosmic_rays"].parameters}
    main_window._run_process("imtools.cosmic_rays", default_params)
    assert "imagen" in main_window.statusBar().currentMessage().lower()


def test_process_dropped_on_view_selects_it_in_properties(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "drop_test.fits")
    qapp.processEvents()
    view = sub_window.widget()

    main_window._on_process_dropped("photometry.aperture", view)
    qapp.processEvents()

    assert main_window.mdi.activeSubWindow() is sub_window
    assert main_window.properties.current_process is main_window._process_by_id["photometry.aperture"]


def test_stf_toggle_does_not_raise(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "stf_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    view = sub_window.widget()
    assert view.stf_enabled is True
    main_window._toggle_active_stf()
    assert view.stf_enabled is False
    main_window._toggle_active_stf()
    assert view.stf_enabled is True
