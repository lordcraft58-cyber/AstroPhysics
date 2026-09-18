"""Prueba de humo de la selección de posiciones sobre la imagen
(continuación de la Fase 9.6): clic real para marcar posiciones, y el
flujo completo main_window -> picking -> proceso real (PSF, traza
espectral) de principio a fin, incluido el hilo de fondo.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import Qt, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

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


def test_image_view_picking_marks_points_and_finishes_on_right_click(qapp, main_window):
    data = np.full((80, 80), 100.0)
    sub_window = main_window.add_image_window(data, "pick_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    received: dict = {}
    view.picking_finished.connect(lambda points: received.update(points=points))

    view.start_picking()
    assert view._picking is True

    _click(view, 10, 15, Qt.MouseButton.LeftButton)
    _click(view, 40, 45, Qt.MouseButton.LeftButton)
    assert len(view._picked_points) == 2
    assert len(view._picked_markers) == 2

    _click(view, 0, 0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    assert view._picking is False
    assert "points" in received
    assert len(received["points"]) == 2
    assert received["points"][0] == pytest.approx((10.0, 15.0), abs=1.0)
    assert received["points"][1] == pytest.approx((40.0, 45.0), abs=1.0)
    assert len(view._picked_markers) == 0  # los marcadores se limpian al terminar


def test_image_view_picking_auto_finishes_at_max_points(qapp, main_window):
    data = np.full((60, 60), 100.0)
    sub_window = main_window.add_image_window(data, "pick_max_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    received: dict = {}
    view.picking_finished.connect(lambda points: received.update(points=points))

    view.start_picking(max_points=1)
    _click(view, 25, 25, Qt.MouseButton.LeftButton)
    qapp.processEvents()

    assert view._picking is False  # terminó sola al alcanzar max_points
    assert received["points"] == [pytest.approx((25.0, 25.0), abs=1.0)]


def test_image_view_picking_cancelled_emits_empty_list(qapp, main_window):
    data = np.full((40, 40), 100.0)
    sub_window = main_window.add_image_window(data, "pick_cancel_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    received: dict = {}
    view.picking_finished.connect(lambda points: received.update(points=points))

    view.start_picking()
    _click(view, 0, 0, Qt.MouseButton.RightButton)  # termina sin marcar nada

    assert received["points"] == []


def _psf_field(shape=(61, 61), *, x0=30.0, y0=30.0, sigma=2.0, flux=30000.0, background=100.0):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    return background + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))


def test_psf_photometry_process_runs_end_to_end_via_click(qapp, main_window):
    true_flux = 30000.0
    data = _psf_field(flux=true_flux)
    sub_window = main_window.add_image_window(data, "star_field.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["photometry.psf"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("photometry.psf", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 30.0, 30.0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert view._picking is False
    assert main_window.properties.apply_button.isEnabled()


def test_psf_empirical_process_runs_end_to_end_via_two_click_stages(qapp, main_window):
    shape = (81, 81)
    sigma = 2.0
    reference_flux, target_flux = 30000.0, 18000.0
    ref_x, ref_y = 25.0, 25.0
    tgt_x, tgt_y = 55.0, 55.0
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    data = np.full(shape, 100.0)
    for x0, y0, flux in ((ref_x, ref_y, reference_flux), (tgt_x, tgt_y, target_flux)):
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    sub_window = main_window.add_image_window(data, "empirical_psf_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["photometry.psf"]
    params = {p.name: p.default for p in process.parameters}
    params["use_empirical_psf"] = True
    main_window._run_process("photometry.psf", params)
    qapp.processEvents()
    assert view._picking is True  # etapa 1: estrellas de referencia

    _click(view, ref_x, ref_y, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina la etapa 1
    qapp.processEvents()
    assert view._picking is True  # etapa 2: fuentes a medir, arrancó sola

    _click(view, tgt_x, tgt_y, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina la etapa 2
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert view._picking is False
    assert main_window.properties.apply_button.isEnabled()


def test_psf_empirical_process_cancelled_at_reference_stage_does_not_run_worker(qapp, main_window):
    data = _psf_field()
    sub_window = main_window.add_image_window(data, "empirical_cancel_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["photometry.psf"]
    params = {p.name: p.default for p in process.parameters}
    params["use_empirical_psf"] = True
    main_window._run_process("photometry.psf", params)
    qapp.processEvents()

    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # cancela la etapa 1 sin marcar nada
    qapp.processEvents()

    assert main_window._active_worker is None
    assert main_window.properties.apply_button.isEnabled()


def test_spectral_trace_process_runs_end_to_end_via_click(qapp, main_window):
    height, width = 41, 150
    yy, xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile
    sub_window = main_window.add_image_window(data, "spectrum.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    windows_before = len(main_window.mdi.subWindowList())
    process = main_window._process_by_id["spectroscopy.trace"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.trace", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)  # un único clic: termina sola (requires_picking=1)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert len(main_window.mdi.subWindowList()) == windows_before + 1  # la traza extraída abre una ventana nueva
    spectrum_view = main_window.mdi.subWindowList()[-1].widget()
    assert isinstance(spectrum_view, SpectrumView)
    assert spectrum_view._data.series[0].y.size == width


def _two_object_spectral_field(height=60, width=150, *, centers=(15.0, 45.0), fluxes=(3000.0, 5000.0)):
    rows = np.arange(height)[:, np.newaxis]
    data = np.full((height, width), 80.0)
    for center, flux in zip(centers, fluxes):
        profile = np.exp(-((rows - center) ** 2) / (2 * 2.0**2))
        profile /= profile.sum(axis=0, keepdims=True)
        data = data + flux * profile
    return data


def test_multi_aperture_process_auto_detects_and_extracts_two_real_objects(qapp, main_window):
    data = _two_object_spectral_field()
    sub_window = main_window.add_image_window(data, "multi_object_spectrum.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    process = main_window._process_by_id["spectroscopy.multiaperture"]
    params = {p.name: p.default for p in process.parameters}
    assert params["auto_detect"] is True

    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("spectroscopy.multiaperture", params)  # auto_detect=True: nunca entra en picking

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert len(main_window.mdi.subWindowList()) == windows_before + 1  # las dos aperturas extraídas abren una ventana nueva
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 2
    spectrum_view = main_window.mdi.subWindowList()[-1].widget()
    assert isinstance(spectrum_view, SpectrumView)
    assert len(spectrum_view._data.series) == 2


def test_multi_aperture_process_runs_via_two_manual_clicks(qapp, main_window):
    data = _two_object_spectral_field()
    sub_window = main_window.add_image_window(data, "multi_object_manual.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["spectroscopy.multiaperture"]
    params = {p.name: p.default for p in process.parameters}
    params["auto_detect"] = False
    main_window._run_process("spectroscopy.multiaperture", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 0.0, 15.0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 45.0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina la marca manual (requires_picking=0)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 2
    spectrum_view = main_window.mdi.subWindowList()[-1].widget()
    assert isinstance(spectrum_view, SpectrumView)
    assert len(spectrum_view._data.series) == 2


def test_line_measurement_process_runs_end_to_end_via_click(qapp, main_window):
    height, width = 41, 200
    columns = np.arange(width, dtype=np.float64)
    line_pixel, continuum_level, line_amplitude = 100.0, 500.0, 4000.0
    row = continuum_level + line_amplitude * np.exp(-((columns - line_pixel) ** 2) / (2 * 3.0**2))
    data = np.tile(row, (height, 1))
    sub_window = main_window.add_image_window(data, "line_measurement.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["spectroscopy.line"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.line", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, line_pixel, height / 2.0, Qt.MouseButton.LeftButton)  # un único clic: termina sola (requires_picking=1)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert main_window.properties.apply_button.isEnabled()
    assert main_window._last_result_table is not None
    row_values = main_window._last_result_table.rows[0]
    center_px = row_values[0]
    assert center_px == pytest.approx(line_pixel, abs=2.0)

    spectrum_view = main_window.mdi.subWindowList()[-1].widget()
    assert isinstance(spectrum_view, SpectrumView)
    assert len(spectrum_view._data.markers) == 1


def test_picking_process_cancelled_does_not_run_worker(qapp, main_window):
    data = _psf_field()
    sub_window = main_window.add_image_window(data, "cancel_flow.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["photometry.psf"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("photometry.psf", params)
    qapp.processEvents()

    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # cancela sin marcar nada
    qapp.processEvents()

    assert main_window._active_worker is None
    assert main_window.properties.apply_button.isEnabled()
