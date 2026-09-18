"""Prueba de humo de extremo a extremo del registro por pares de
estrellas emparejadas a clic (Fase 18, bloque astrometría): dos ventanas
MDI reales, clic real en cada una (mismo orden), ajuste afín real
(`fit_affine_transform`) y remuestreo real (`apply_affine_transform`),
con el hilo de fondo real -- sin WCS en ninguna de las dos imágenes (a
diferencia de "Registrar por WCS compartido...").

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


def _star_field(shape, positions, *, amplitude=5000.0, sigma=1.8, background=100.0):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, background, dtype=np.float64)
    for x, y in positions:
        field += amplitude * np.exp(-(((xx - x) ** 2 + (yy - y) ** 2)) / (2 * sigma**2))
    return field


_REFERENCE_POSITIONS = [(20.0, 20.0), (60.0, 25.0), (35.0, 55.0)]
_SHIFT = (8.0, -4.0)  # traslación pura conocida aplicada a la imagen "target"
_TARGET_POSITIONS = [(x + _SHIFT[0], y + _SHIFT[1]) for x, y in _REFERENCE_POSITIONS]


def _wait_for_worker(qapp, main_window, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def test_star_pair_registration_flow_aligns_translated_field_end_to_end(qapp, main_window):
    from qt_app.astrometry.star_pair_registration_dialog import StarPairConfigDialog

    shape = (90, 90)
    reference_data = _star_field(shape, _REFERENCE_POSITIONS)
    target_data = _star_field(shape, _TARGET_POSITIONS)

    reference_window = main_window.add_image_window(reference_data, "star_pair_reference.fits")
    target_window = main_window.add_image_window(target_data, "star_pair_target.fits")
    main_window.mdi.setActiveSubWindow(reference_window)
    qapp.processEvents()
    reference_view = reference_window.widget()
    target_view = target_window.widget()

    captured = {}
    original_exec = StarPairConfigDialog.exec

    def _capture_and_accept(self):
        captured["dialog"] = self
        self.reference_combo.setCurrentText("star_pair_reference.fits")
        self.target_combo.setCurrentText("star_pair_target.fits")
        self.n_pairs_spin.setValue(3)
        return StarPairConfigDialog.DialogCode.Accepted

    StarPairConfigDialog.exec = _capture_and_accept
    try:
        main_window._open_star_pair_registration_dialog()
        qapp.processEvents()
    finally:
        StarPairConfigDialog.exec = original_exec

    assert reference_view._picking is True
    for x, y in _REFERENCE_POSITIONS:
        _click(reference_view, x, y, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert reference_view._picking is False  # terminó sola al alcanzar los 3 pares
    assert target_view._picking is True

    for x, y in _TARGET_POSITIONS:
        _click(target_view, x, y, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    assert target_view._picking is False

    windows_before = len(main_window.mdi.subWindowList())
    _wait_for_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    result_view = main_window.mdi.subWindowList()[-1].widget()
    assert "pares con star_pair_reference.fits" in main_window.mdi.subWindowList()[-1].windowTitle()

    # el resultado remuestreado debe alinear los picos con las posiciones REALES de referencia
    for x, y in _REFERENCE_POSITIONS:
        window = result_view.data[int(round(y)) - 2 : int(round(y)) + 3, int(round(x)) - 2 : int(round(x)) + 3]
        assert window.max() > 2000.0  # el pico de la estrella sigue ahí, alineado

    assert "completado" in main_window.statusBar().currentMessage().lower()


def test_star_pair_registration_reports_too_few_reference_points(qapp, main_window):
    from qt_app.astrometry.star_pair_registration_dialog import StarPairConfigDialog

    shape = (60, 60)
    reference_window = main_window.add_image_window(_star_field(shape, _REFERENCE_POSITIONS), "few_ref.fits")
    main_window.add_image_window(_star_field(shape, _TARGET_POSITIONS), "few_target.fits")
    main_window.mdi.setActiveSubWindow(reference_window)
    qapp.processEvents()
    reference_view = reference_window.widget()

    original_exec = StarPairConfigDialog.exec

    def _accept_with_defaults(self):
        self.reference_combo.setCurrentText("few_ref.fits")
        self.target_combo.setCurrentText("few_target.fits")
        self.n_pairs_spin.setValue(5)  # pide 5, pero solo se marcarán 2 antes de terminar a mano
        return StarPairConfigDialog.DialogCode.Accepted

    StarPairConfigDialog.exec = _accept_with_defaults
    try:
        main_window._open_star_pair_registration_dialog()
        qapp.processEvents()
    finally:
        StarPairConfigDialog.exec = original_exec

    _click(reference_view, 20.0, 20.0, Qt.MouseButton.LeftButton)
    _click(reference_view, 60.0, 25.0, Qt.MouseButton.LeftButton)
    _click(reference_view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina antes de tiempo, con solo 2
    qapp.processEvents()

    assert "al menos 3 pares" in main_window.statusBar().currentMessage().lower()
    assert main_window._active_worker is None


def test_star_pair_registration_without_second_image_warns(qapp, main_window):
    for sub_window in list(main_window.mdi.subWindowList()):
        sub_window.close()
    qapp.processEvents()
    main_window.add_image_window(np.full((40, 40), 100.0), "only_one.fits")
    qapp.processEvents()

    main_window._open_star_pair_registration_dialog()

    assert "dos imágenes" in main_window.statusBar().currentMessage().lower()
