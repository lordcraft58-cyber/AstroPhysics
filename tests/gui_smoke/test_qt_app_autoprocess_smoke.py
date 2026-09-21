"""Prueba de humo de extremo a extremo del autoproceso de espectro (§34):
un único clic encadena traza -> extracción -> calibración por estrella de
referencia -> identificación de líneas -> informe de calidad, y el
resultado se enhebra en la ventana igual que ya hace 'Calibrar por
estrella de referencia' por separado (misma clave de artefacto
`wavelength_calibration_record`, ver `main_window._on_process_finished`).

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


def _synthetic_2d_star_frame(shape=(41, 2000), *, wave0=4000.0, dispersion=2.0):
    from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES

    rng = np.random.default_rng(23)
    height, width = shape
    pixel = np.arange(width, dtype=np.float64)
    flux_per_col = np.full(width, 6000.0)
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - wave0) / dispersion
        if 0 <= true_pixel < width:
            flux_per_col -= 1200.0 * np.exp(-((pixel - true_pixel) ** 2) / (2 * 2.5**2))
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - 20.0) ** 2) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 50.0 + flux_per_col[np.newaxis, :] * profile
    data = data + rng.normal(0, 3.0, shape)
    return data


def test_autoprocess_spectrum_process_runs_end_to_end_via_click_and_wires_the_calibration_back_onto_the_view(qapp, main_window):
    wave0, dispersion = 4000.0, 2.0
    data = _synthetic_2d_star_frame(wave0=wave0, dispersion=dispersion)
    sub_window = main_window.add_image_window(data, "autoprocess.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    windows_before = len(main_window.mdi.subWindowList())

    process = main_window._process_by_id["spectroscopy.autoprocess"]
    params = {p.name: p.default for p in process.parameters}
    params["approx_dispersion_angstrom_per_px"] = dispersion * 1.01
    params["approx_wavelength_at_pixel0"] = wave0 + 10.0
    params["calibration_tolerance_angstrom"] = 40.0
    params["identify_tolerance_angstrom"] = 40.0
    main_window._run_process("spectroscopy.autoprocess", params)
    qapp.processEvents()
    assert view._picking is True

    _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)
    qapp.processEvents()
    _wait_active_worker(qapp, main_window)

    # el autoproceso abre una ventana de espectro nueva (como 'Extracción de traza'),
    # nunca una imagen -- solo +1 ventana sobre la imagen de entrada.
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 6  # informe de calidad (§31/§42)

    # la calibración en longitud de onda real se enhebró de vuelta sobre la
    # VISTA DE ORIGEN (no la ventana de espectro nueva) -- mismo mecanismo
    # que ya usa 'Calibrar por estrella de referencia' por separado.
    assert view.fitted_wavelength_solution is not None
    assert view.wavelength_calibration_record is not None
    assert view.wavelength_calibration_record.reference_object
    assert view.fitted_wavelength_solution.pixel_to_wavelength(0.0) == pytest.approx(wave0, abs=5.0)
    assert len(view._trace_overlay_items) > 0
