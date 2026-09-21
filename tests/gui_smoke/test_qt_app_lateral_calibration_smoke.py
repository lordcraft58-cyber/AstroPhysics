"""Prueba de humo de extremo a extremo del canal de calibración
lateral/simultánea (§14) dentro de "Corrección de flexión espectral
entre exposiciones...": mide un desplazamiento real conocido usando el
canal de calibración (en vez de la fila central del objeto), reutiliza
la traza YA calculada (`view.trace_edit_context`, slice 29) sin
retrazar, y dibuja la región real del canal sobre el overlay.

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


def _wait_active_worker(qapp, main_window, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


_OBJECT_CENTER = 20.0
_CALIBRATION_OFFSET = -15.0
_LINES = (200.0, 500.0, 800.0)
_TRUE_SHIFT_PX = 3.0


def _synthetic_frame_with_lateral_calibration(*, height=41, width=1000, shift=0.0, seed=5):
    rng = np.random.default_rng(seed)
    rows = np.arange(height, dtype=np.float64)[:, np.newaxis]
    columns = np.arange(width, dtype=np.float64)

    object_profile = np.exp(-((rows - _OBJECT_CENTER) ** 2) / (2 * 2.0**2))
    object_profile /= object_profile.sum(axis=0, keepdims=True)
    object_flux = np.full(width, 3000.0)

    calibration_center = _OBJECT_CENTER + _CALIBRATION_OFFSET
    calibration_profile = np.exp(-((rows - calibration_center) ** 2) / (2 * 2.0**2))
    calibration_profile /= calibration_profile.sum(axis=0, keepdims=True)
    calibration_flux = np.full(width, 500.0)
    for p in _LINES:
        idx = int(round(p + shift))
        calibration_flux[idx - 2 : idx + 3] += np.array([80.0, 600.0, 1500.0, 600.0, 80.0])

    data = 50.0 + object_profile * object_flux[np.newaxis, :] + calibration_profile * calibration_flux[np.newaxis, :]
    data = data + rng.normal(0, 1.0, (height, width))
    _ = columns  # eje de dispersión ya implícito en el ancho de los arrays -- no se usa por sí solo
    return data


def _traced_view(qapp, main_window, *, shift: float, title: str):
    data = _synthetic_frame_with_lateral_calibration(shift=shift)
    sub_window = main_window.add_image_window(data, title)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["spectroscopy.trace"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.trace", params)
    qapp.processEvents()
    _click(view, 0.0, _OBJECT_CENTER, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    _wait_active_worker(qapp, main_window)
    assert view.trace_edit_context is not None
    return view


def test_flexure_dialog_measures_a_known_shift_using_the_lateral_calibration_channel(qapp, main_window):
    from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.flexure_correction_dialog import FlexureCorrectionDialog

    ref_view = _traced_view(qapp, main_window, shift=0.0, title="lateral_reference.fits")
    new_view = _traced_view(qapp, main_window, shift=_TRUE_SHIFT_PX, title="lateral_new.fits")

    solution = fit_wavelength_solution(list(_LINES), [4780.0, 5200.0, 5620.0], degree=1)
    ref_view.fitted_wavelength_solution = solution
    ref_view.wavelength_calibration_record = WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=3, lamp_name="Ne"
    )

    views = {"lateral_reference.fits": ref_view, "lateral_new.fits": new_view}
    dialog = FlexureCorrectionDialog(views, main_window)
    dialog.reference_combo.setCurrentText("lateral_reference.fits")
    dialog.new_combo.setCurrentText("lateral_new.fits")
    dialog.reference_wavelength_spin.setValue(5200.0)
    dialog.use_lateral_calibration_checkbox.setChecked(True)
    dialog.calibration_offset_spin.setValue(_CALIBRATION_OFFSET)
    dialog.calibration_half_width_spin.setValue(6.0)

    dialog._on_measure()

    assert dialog._last_result is not None
    assert dialog._last_result.shift_px == pytest.approx(_TRUE_SHIFT_PX, abs=0.6)

    # el canal real usado queda dibujado sobre el overlay de las dos ventanas (§14)
    assert ref_view._trace_overlay_single.calibration_windows
    assert new_view._trace_overlay_single.calibration_windows
    assert ref_view._trace_overlay_single.calibration_windows[0].offset_px == pytest.approx(_CALIBRATION_OFFSET)


def test_flexure_dialog_lateral_calibration_requires_a_real_trace_first(qapp, main_window):
    from qt_app.spectroscopy.flexure_correction_dialog import FlexureCorrectionDialog

    # ventanas SIN trazar -- nunca se han pasado por "Extracción de traza"
    ref_data = _synthetic_frame_with_lateral_calibration(shift=0.0)
    new_data = _synthetic_frame_with_lateral_calibration(shift=_TRUE_SHIFT_PX)
    ref_sub = main_window.add_image_window(ref_data, "untraced_reference.fits")
    new_sub = main_window.add_image_window(new_data, "untraced_new.fits")
    qapp.processEvents()

    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

    ref_view = ref_sub.widget()
    ref_view.fitted_wavelength_solution = fit_wavelength_solution(list(_LINES), [4780.0, 5200.0, 5620.0], degree=1)

    views = {"untraced_reference.fits": ref_view, "untraced_new.fits": new_sub.widget()}
    dialog = FlexureCorrectionDialog(views, main_window)
    dialog.reference_combo.setCurrentText("untraced_reference.fits")
    dialog.new_combo.setCurrentText("untraced_new.fits")
    dialog.use_lateral_calibration_checkbox.setChecked(True)

    dialog._on_measure()

    assert dialog._last_result is None
    assert "traza real" in dialog.result_label.text()
