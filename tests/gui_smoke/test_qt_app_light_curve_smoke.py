"""Prueba de humo de extremo a extremo de la curva de luz multiépoca
(Estrellas Variables -> Curva de luz multiépoca...): clic para marcar la
variable + comparación sobre el fotograma de referencia ya abierto,
añadir más LIGHTS reales desde disco, calcular con el hilo de fondo
real, y comprobar el resultado (gráfico PNG real embebido + tabla
exportable).

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import math
import time
from datetime import datetime, timedelta

import numpy as np
import pytest
from astropy.io import fits

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


def _star(shape, x0, y0, flux, sigma=2.2):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    return flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))


def _write_frame(path, *, shape, target_xy, comp_xy, target_flux, comp_flux, date_obs, shift=(0.0, 0.0)):
    dx, dy = shift
    data = np.full(shape, 100.0)
    data = data + _star(shape, target_xy[0] + dx, target_xy[1] + dy, target_flux)
    data = data + _star(shape, comp_xy[0] + dx, comp_xy[1] + dy, comp_flux)
    rng = np.random.default_rng(int(date_obs.timestamp()) % 1000)
    data = data + rng.normal(0, 1.0, size=shape)
    header = fits.Header()
    header["DATE-OBS"] = date_obs.strftime("%Y-%m-%dT%H:%M:%S")
    fits.PrimaryHDU(data=data.astype(np.float32), header=header).writeto(path, overwrite=True)
    return data, dict(header)


def test_light_curve_dialog_computes_a_real_declining_trend_from_disk_lights(qapp, main_window, tmp_path):
    from qt_app.variable_stars.light_curve_dialog import LightCurveDialog

    shape = (120, 120)
    target_xy = (40.0, 40.0)
    comp_xy = (80.0, 70.0)
    base_time = datetime(2024, 8, 1, 0, 0, 0)

    frame_paths = []
    for i in range(4):
        path = tmp_path / f"light_{i}.fits"
        data, header = _write_frame(
            path, shape=shape, target_xy=target_xy, comp_xy=comp_xy,
            target_flux=60000.0 - 1500.0 * i, comp_flux=40000.0,
            date_obs=base_time + timedelta(minutes=10 * i),
        )
        frame_paths.append(str(path))
        if i == 0:
            ref_data, ref_header = data, header

    sub_window = main_window.add_image_window(ref_data, "light_0.fits", header=ref_header, source_path=frame_paths[0])
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    main_window._open_light_curve_flow()
    qapp.processEvents()
    assert view._picking is True

    _click(view, target_xy[0], target_xy[1], Qt.MouseButton.LeftButton)
    _click(view, comp_xy[0], comp_xy[1], Qt.MouseButton.LeftButton)
    qapp.processEvents()

    captured = {}
    original_exec = LightCurveDialog.exec

    def _fill_and_run(self):
        captured["dialog"] = self
        for path in frame_paths[1:]:
            self._extra_paths.append(path)
        self._on_run()
        deadline = time.monotonic() + 10.0
        while self._worker is not None and self._worker.isRunning() and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        qapp.processEvents()
        return LightCurveDialog.DialogCode.Accepted

    LightCurveDialog.exec = _fill_and_run
    try:
        _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina la selección -> abre el diálogo
        qapp.processEvents()
    finally:
        LightCurveDialog.exec = original_exec

    assert view._picking is False
    dialog = captured["dialog"]
    assert dialog._result is not None
    assert dialog._result.n_valid_epochs == 4
    assert dialog._result.temporal_evidence.variable_candidate is True
    assert dialog._chart_png is not None
    assert dialog._chart_png[:8] == b"\x89PNG\r\n\x1a\n"  # cabecera real de un PNG, no un placeholder
    assert dialog.save_image_button.isEnabled()
    assert dialog.export_csv_button.isEnabled()

    assert dialog.result_table() is not None
    assert len(dialog.result_table().rows) == 4

    csv_path = tmp_path / "curva.csv"
    dialog.result_table().to_csv(str(csv_path))
    assert csv_path.exists()
    assert "mag_diferencial" in csv_path.read_text()


def test_light_curve_flow_without_an_active_image_reports_a_clear_message(qapp, main_window):
    main_window._open_light_curve_flow()
    assert "LIGHT" in main_window.statusBar().currentMessage() or "imagen" in main_window.statusBar().currentMessage().lower()


def test_light_curve_flow_rejects_a_single_click_with_no_comparison(qapp, main_window):
    shape = (60, 60)
    data = np.full(shape, 100.0) + _star(shape, 30.0, 30.0, 50000.0)
    sub_window = main_window.add_image_window(data, "single.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    main_window._open_light_curve_flow()
    qapp.processEvents()
    _click(view, 30.0, 30.0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    assert view._picking is False
    assert "2" in main_window.statusBar().currentMessage()
