"""Prueba de humo de extremo a extremo de la magnitud fotométrica
sintética (menú Espectroscopía -> "Magnitud fotométrica sintética..."):
carga real de una curva de filtro desde un archivo de dos columnas +
cálculo de magnitud AB real sobre un espectro sintético con f_nu
constante conocido.

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


def _flat_f_nu_image(f_nu_jy=3631.0, *, height=21, width=2000, wl_min=4000.0, wl_max=7000.0):
    import astropy.units as u

    wavelength = np.linspace(wl_min, wl_max, width)
    flux = (f_nu_jy * u.Jy).to(
        u.erg / u.s / u.cm**2 / u.AA, equivalencies=u.spectral_density(wavelength * u.AA)
    ).value
    row = np.tile(flux, (height, 1))
    return row, wavelength


def test_synthetic_photometry_dialog_computes_a_real_ab_magnitude(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.synthetic_photometry_dialog import SyntheticPhotometryDialog

    data, wavelength = _flat_f_nu_image()
    sub_window = main_window.add_image_window(data, "flat_ab0.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    filter_path = tmp_path / "tophat.dat"
    filter_wavelength = np.linspace(5000.0, 6000.0, 200)
    filter_path.write_text("\n".join(f"{w:.2f} 1.0" for w in filter_wavelength))

    dialog = SyntheticPhotometryDialog(view, main_window)
    from PySide6.QtWidgets import QFileDialog

    original_get_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(filter_path), ""))
    try:
        dialog._on_load_filter()
    finally:
        QFileDialog.getOpenFileName = original_get_open

    assert dialog._filter_curve is not None
    dialog._on_compute()

    assert dialog._last_magnitude is not None
    assert dialog._last_magnitude == pytest.approx(0.0, abs=1e-2)
    assert "m_AB" in dialog.result_label.text()

    table = dialog.result_table()
    assert table is not None
    assert len(table.rows) == 1


def test_synthetic_photometry_dialog_without_a_filter_warns_instead_of_crashing(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.synthetic_photometry_dialog import SyntheticPhotometryDialog

    data, wavelength = _flat_f_nu_image()
    sub_window = main_window.add_image_window(data, "no_filter.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    dialog = SyntheticPhotometryDialog(view, main_window)
    dialog._on_compute()

    assert "curva" in dialog.result_label.text().lower()
    assert dialog._last_magnitude is None


def test_synthetic_photometry_dialog_reports_incomplete_coverage_honestly(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.synthetic_photometry_dialog import SyntheticPhotometryDialog

    # el espectro solo cubre 5900-6000 A -- el filtro pide 5000-6000
    data, wavelength = _flat_f_nu_image(wl_min=5900.0, wl_max=6000.0, width=200)
    sub_window = main_window.add_image_window(data, "narrow_spectrum.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    filter_path = tmp_path / "tophat_wide.dat"
    filter_wavelength = np.linspace(5000.0, 6000.0, 200)
    filter_path.write_text("\n".join(f"{w:.2f} 1.0" for w in filter_wavelength))

    dialog = SyntheticPhotometryDialog(view, main_window)
    from PySide6.QtWidgets import QFileDialog

    original_get_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (str(filter_path), ""))
    try:
        dialog._on_load_filter()
    finally:
        QFileDialog.getOpenFileName = original_get_open
    dialog._on_compute()

    assert dialog._last_magnitude is None
    assert "no cubre" in dialog.result_label.text().lower()


def test_synthetic_photometry_menu_action_requires_a_wavelength_calibration(qapp, main_window):
    data, _wavelength = _flat_f_nu_image()
    sub_window = main_window.add_image_window(data, "uncalibrated.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    main_window._open_synthetic_photometry_dialog()

    assert "calibra" in main_window.statusBar().currentMessage().lower()
