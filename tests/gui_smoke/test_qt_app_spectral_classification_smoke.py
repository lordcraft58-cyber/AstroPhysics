"""Prueba de humo de extremo a extremo de la clasificación espectral en
vivo contra el atlas real (estilo Vireo): navegar la lista de estándares
actualiza los tres paneles sin pulsar ningún botón adicional.

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


_TRUE_PIXELS = (40.0, 110.0, 190.0, 260.0)
_TRUE_WAVELENGTHS = (4046.6, 4358.3, 5460.7, 5769.6)


def _synthetic_arc_row(width=300, height=21):
    row = np.full(width, 100.0)
    for pixel in _TRUE_PIXELS:
        idx = int(round(pixel))
        row[idx - 2 : idx + 3] += [50, 400, 1200, 400, 50]
    return np.tile(row, (height, 1))


def test_spectral_classification_dialog_updates_live_when_browsing_the_real_atlas(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_classification.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    assert dialog.standards_list.count() == 161

    dialog.standards_list.setCurrentRow(0)
    qapp.processEvents()

    assert len(dialog.standard_view._data.series) == 1
    assert len(dialog.observed_view._data.series) == 1
    assert len(dialog.result_view._data.series) == 1
    assert "solape real" in dialog.status_label.text()

    # navegar a otro estándar sin pulsar nada más debe recalcular
    first_standard_flux = dialog.standard_view._data.series[0].y.copy()
    dialog.standards_list.setCurrentRow(100)
    qapp.processEvents()
    second_standard_flux = dialog.standard_view._data.series[0].y
    assert not np.array_equal(first_standard_flux, second_standard_flux)


def test_spectral_classification_dialog_divide_operation_produces_a_real_ratio(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_divide.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    dialog.standards_list.setCurrentRow(0)
    dialog.operation_combo.setCurrentIndex(1)  # cociente
    qapp.processEvents()

    assert "Cociente" in dialog.result_view._data.y_label


def test_spectral_classification_dialog_marks_known_chemical_lines_by_default(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_markers.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    assert dialog.lines_checkbox.isChecked()
    dialog.standards_list.setCurrentRow(0)
    qapp.processEvents()
    assert len(dialog.observed_view._data.markers) > 0

    dialog.lines_checkbox.setChecked(False)
    qapp.processEvents()
    assert len(dialog.observed_view._data.markers) == 0


def test_spectral_classification_dialog_requires_a_calibrated_observed_window(qapp, main_window):
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "uncalibrated_for_classification.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    dialog.standards_list.setCurrentRow(0)
    qapp.processEvents()
    assert "calibración" in dialog.status_label.text().lower()
