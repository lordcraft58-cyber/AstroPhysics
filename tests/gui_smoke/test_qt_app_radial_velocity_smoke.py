"""Prueba de humo de extremo a extremo de la velocidad radial multi-línea
+ corrección baricéntrica/heliocéntrica (menú Espectroscopía -> "Medir
velocidad radial..."), sobre un espectro 2D sintético con líneas de
Balmer reales desplazadas por una velocidad conocida.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

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


_C_KM_S = 299792.458
_BALMER_REST = (6562.8, 4861.3, 4340.5, 4101.7)
_TRUE_VELOCITY_KM_S = 95.0


def _synthetic_absorption_row(width=3000, height=21, *, seed=7):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(3800.0, 7200.0, width)
    continuum = 100.0 + 0.001 * (wavelength - 5500.0)
    flux = continuum.copy()
    for rest in _BALMER_REST:
        observed = rest * (1.0 + _TRUE_VELOCITY_KM_S / _C_KM_S)
        flux -= 15.0 * np.exp(-((wavelength - observed) ** 2) / (2 * 1.2**2))
    flux += rng.normal(0, 0.15, width)
    row = flux
    return np.tile(row, (height, 1)), wavelength


def test_radial_velocity_dialog_recovers_a_known_velocity_from_balmer_lines(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.radial_velocity_dialog import RadialVelocityDialog

    data, wavelength = _synthetic_absorption_row()
    sub_window = main_window.add_image_window(data, "rv_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    pixels = [0.0, float(data.shape[1] - 1)]
    known_wavelengths = [float(wavelength[0]), float(wavelength[-1])]
    view.fitted_wavelength_solution = fit_wavelength_solution(pixels, known_wavelengths, degree=1)

    dialog = RadialVelocityDialog(view, main_window)
    dialog.window_halfwidth_spin.setValue(6.0)
    dialog.continuum_reject_combo.setCurrentText("absorption")
    dialog._on_measure()

    assert dialog.table.rowCount() == len(_BALMER_REST)
    assert dialog._last_result is not None
    assert dialog._last_result.n_lines_used == len(_BALMER_REST)
    assert dialog._last_result.combined_velocity_km_s == pytest.approx(_TRUE_VELOCITY_KM_S, abs=8.0)
    assert "km/s" in dialog.summary_label.text()

    table = dialog.result_table()
    assert table is not None
    assert len(table.rows) == len(_BALMER_REST)


def test_radial_velocity_dialog_without_obstime_warns_instead_of_crashing(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.radial_velocity_dialog import RadialVelocityDialog

    data, wavelength = _synthetic_absorption_row()
    sub_window = main_window.add_image_window(data, "rv_no_obstime.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    dialog = RadialVelocityDialog(view, main_window)
    dialog._on_compute_correction()

    assert "instante" in dialog.correction_label.text().lower()


def test_radial_velocity_dialog_applies_a_real_barycentric_correction(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.radial_velocity_dialog import RadialVelocityDialog

    data, wavelength = _synthetic_absorption_row()
    sub_window = main_window.add_image_window(data, "rv_helio.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    dialog = RadialVelocityDialog(view, main_window)
    dialog._on_measure()
    dialog.ra_spin.setValue(279.23473479)
    dialog.dec_spin.setValue(38.78368896)
    dialog.obstime_combo.setCurrentText("2024-06-01T00:00:00")
    dialog.obs_lon_spin.setValue(-2.546111)
    dialog.obs_lat_spin.setValue(37.223611)
    dialog.obs_height_spin.setValue(2168.0)
    dialog._on_compute_correction()

    assert dialog._last_correction is not None
    assert abs(dialog._last_correction.correction_km_s) < 31.0
    assert "corrección" in dialog.correction_label.text().lower()
    assert "km/s" in dialog.correction_label.text()


def test_radial_velocity_menu_action_requires_a_wavelength_calibration(qapp, main_window):
    data, _ = _synthetic_absorption_row()
    sub_window = main_window.add_image_window(data, "rv_uncalibrated.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    main_window._open_radial_velocity_dialog()

    assert "calibra" in main_window.statusBar().currentMessage().lower()
