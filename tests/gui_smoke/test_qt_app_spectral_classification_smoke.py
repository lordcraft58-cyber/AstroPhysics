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


def _calibrate_view(view, data, *, extracted_spectrum=None):
    # Misma sincronía que el código real (main_window._on_wavelength_
    # fitted/_on_process_finished): fitted_wavelength_solution SIEMPRE
    # va acompañado del espectro real ya extraído, nunca solo uno de los dos.
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)
    if extracted_spectrum is None:
        extracted_spectrum = data[data.shape[0] // 2, :].astype(float)
    view.wavelength_calibration_spectrum = extracted_spectrum


def test_spectral_classification_dialog_updates_live_when_browsing_the_real_atlas(qapp, main_window):
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_classification.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    _calibrate_view(view, data)

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
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_divide.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    _calibrate_view(view, data)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    dialog.standards_list.setCurrentRow(0)
    dialog.operation_combo.setCurrentIndex(1)  # cociente
    qapp.processEvents()

    assert "Cociente" in dialog.result_view._data.y_label


def test_spectral_classification_dialog_marks_known_chemical_lines_by_default(qapp, main_window):
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_markers.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    _calibrate_view(view, data)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    assert dialog.lines_checkbox.isChecked()
    dialog.standards_list.setCurrentRow(0)
    qapp.processEvents()
    assert len(dialog.observed_view._data.markers) > 0

    dialog.lines_checkbox.setChecked(False)
    qapp.processEvents()
    assert len(dialog.observed_view._data.markers) == 0


def test_spectral_classification_dialog_uses_the_real_extracted_spectrum_not_the_raw_ccd_row(qapp, main_window):
    # Regresión directa del hallazgo real del usuario ("pero compara el
    # continuo no el espectro"): el diálogo debe leer SIEMPRE view.
    # wavelength_calibration_spectrum (el espectro ya extraído con
    # Horne 1986 y resta de cielo), nunca la fila central cruda del
    # fotograma 2D -- aquí las dos son deliberadamente distintas para
    # que cualquier regresión al comportamiento antiguo falle el test.
    from qt_app.spectroscopy.spectral_classification_dialog import SpectralClassificationDialog

    data = _synthetic_arc_row()
    raw_row = data[data.shape[0] // 2, :].astype(float)
    real_extracted_spectrum = raw_row + 5000.0  # inconfundible frente a la fila cruda

    sub_window = main_window.add_image_window(data, "target_for_real_spectrum_check.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    _calibrate_view(view, data, extracted_spectrum=real_extracted_spectrum)

    dialog = SpectralClassificationDialog(main_window._image_views_by_title(), main_window)
    dialog.normalize_combo.setCurrentText("none")
    dialog.standards_list.setCurrentRow(0)
    qapp.processEvents()

    displayed_observed_flux = dialog.observed_view._data.series[0].y
    assert np.allclose(displayed_observed_flux, real_extracted_spectrum)
    assert not np.allclose(displayed_observed_flux, raw_row)


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
