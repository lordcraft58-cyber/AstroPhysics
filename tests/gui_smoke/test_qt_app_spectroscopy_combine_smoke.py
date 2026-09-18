"""Prueba de humo GUI de "Combinar espectros...": diálogo real
(qt_app/spectroscopy/combine_spectra_dialog.py) contra ventanas MDI
reales -- selección a clic (checkboxes), combinación real vía
`combine_spectra`, y apertura de la ventana con el resultado.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import Qt  # noqa: E402
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


def _spectrum_row(width: int, level: float) -> np.ndarray:
    columns = np.arange(width, dtype=np.float64)
    line = 300.0 * np.exp(-((columns - 60.0) ** 2) / (2 * 3.0**2))
    return level + line


def _check_all(dialog) -> None:
    for i in range(dialog.list_widget.count()):
        dialog.list_widget.item(i).setCheckState(Qt.CheckState.Checked)


def test_combine_spectra_dialog_combines_two_open_windows_end_to_end(qapp, main_window):
    from qt_app.spectroscopy.combine_spectra_dialog import CombineSpectraDialog

    width = 120
    data_a = np.tile(_spectrum_row(width, 1000.0), (21, 1))
    data_b = np.tile(_spectrum_row(width, 1000.0), (21, 1))
    main_window.add_image_window(data_a, "exposure_a.fits")
    main_window.add_image_window(data_b, "exposure_b.fits")
    qapp.processEvents()

    views = main_window._image_views_by_title()
    assert set(views) == {"exposure_a.fits", "exposure_b.fits"}

    dialog = CombineSpectraDialog(views, main_window)
    dialog.combined.connect(main_window._on_spectra_combined)
    _check_all(dialog)

    windows_before = len(main_window.mdi.subWindowList())
    dialog._on_combine()
    qapp.processEvents()

    assert dialog.status_label.text().startswith("Combinados 2 espectro(s)")
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == width

    from qt_app.spectroscopy.spectrum_view import SpectrumView

    combined_view = main_window.mdi.subWindowList()[-1].widget()
    assert isinstance(combined_view, SpectrumView)
    expected = _spectrum_row(width, 1000.0)
    np.testing.assert_allclose(combined_view._data.series[0].y, expected, rtol=0.0, atol=1e-6)


def test_combine_spectra_dialog_rejects_mixed_calibration_state(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.combine_spectra_dialog import CombineSpectraDialog

    width = 60
    data_a = np.tile(_spectrum_row(width, 500.0), (21, 1))
    data_b = np.tile(_spectrum_row(width, 500.0), (21, 1))
    sub_a = main_window.add_image_window(data_a, "calibrated.fits")
    main_window.add_image_window(data_b, "uncalibrated.fits")
    qapp.processEvents()

    sub_a.widget().fitted_wavelength_solution = fit_wavelength_solution([0.0, 59.0], [6000.0, 6118.0], degree=1)

    views = main_window._image_views_by_title()
    dialog = CombineSpectraDialog(views, main_window)
    _check_all(dialog)

    dialog._on_combine()

    assert "calibradas y sin calibrar" in dialog.status_label.text()


def test_combine_spectra_menu_action_warns_with_fewer_than_two_images(qapp, main_window):
    main_window.add_image_window(np.full((10, 10), 1.0), "only_one.fits")
    qapp.processEvents()

    main_window._open_combine_spectra_dialog()  # no debe abrir el diálogo ni lanzar excepción

    assert "dos imágenes" in main_window.statusBar().currentMessage()
