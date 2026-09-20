"""Prueba de humo de extremo a extremo de la corrección de flexión
espectral entre exposiciones (menú Espectroscopía -> "Corrección de
flexión entre exposiciones..."): mide un desplazamiento real conocido
entre dos exposiciones de arco sintéticas y lo aplica, guardando un
FITS real con procedencia `offset_only_reidentified`.

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


def _arc_image(*, height=21, width=1000, shift=0.0, seed=3, lines=(200.0, 500.0, 800.0)):
    rng = np.random.default_rng(seed)
    row = np.full(width, 100.0) + rng.normal(0, 2.0, width)
    for p in lines:
        idx = int(round(p + shift))
        row[idx - 2 : idx + 3] += np.array([80, 600, 1500, 600, 80])
    return np.tile(row, (height, 1))


_TRUE_SHIFT_PX = 3.0


def test_flexure_correction_dialog_measures_and_applies_a_known_shift(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.flexure_correction_dialog import FlexureCorrectionDialog

    reference_data = _arc_image(shift=0.0)
    new_data = _arc_image(shift=_TRUE_SHIFT_PX)

    ref_sub = main_window.add_image_window(reference_data, "arc_reference.fits")
    new_sub = main_window.add_image_window(new_data, "arc_new.fits", source_path=str(tmp_path / "arc_new.fits"))
    qapp.processEvents()

    solution = fit_wavelength_solution([200.0, 500.0, 800.0], [4780.0, 5200.0, 5620.0], degree=1)
    ref_view = ref_sub.widget()
    ref_view.fitted_wavelength_solution = solution
    ref_view.wavelength_calibration_record = WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=3, lamp_name="Ne"
    )

    views = {"arc_reference.fits": ref_view, "arc_new.fits": new_sub.widget()}
    dialog = FlexureCorrectionDialog(views, main_window)
    dialog.reference_combo.setCurrentText("arc_reference.fits")
    dialog.new_combo.setCurrentText("arc_new.fits")
    dialog.reference_wavelength_spin.setValue(5200.0)

    dialog._on_measure()

    assert dialog._last_result is not None
    assert dialog._last_result.shift_px == pytest.approx(_TRUE_SHIFT_PX, abs=0.5)
    assert "Δpíxel" in dialog.result_label.text()

    out_path = tmp_path / "arc_new_flexure.fits"
    from PySide6.QtWidgets import QFileDialog

    original_get_save = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_path), ""))
    try:
        dialog._on_save()
    finally:
        QFileDialog.getSaveFileName = original_get_save

    assert out_path.exists()
    from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits

    wavelength_out, flux_out, header_out = load_spectrum1d_fits(str(out_path))
    assert flux_out.shape == (1000,)

    new_view = new_sub.widget()
    assert new_view.wavelength_calibration_record.offset_only_reidentified

    table = dialog.result_table()
    assert table is not None
    assert len(table.rows) == 1


def test_flexure_correction_dialog_rejects_mismatched_widths(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.flexure_correction_dialog import FlexureCorrectionDialog

    reference_data = _arc_image(width=1000)
    narrow_data = _arc_image(width=500, lines=(100.0, 250.0, 400.0))

    ref_sub = main_window.add_image_window(reference_data, "wide.fits")
    narrow_sub = main_window.add_image_window(narrow_data, "narrow.fits")
    qapp.processEvents()

    ref_view = ref_sub.widget()
    ref_view.fitted_wavelength_solution = fit_wavelength_solution([200.0, 800.0], [4780.0, 5620.0], degree=1)

    views = {"wide.fits": ref_view, "narrow.fits": narrow_sub.widget()}
    dialog = FlexureCorrectionDialog(views, main_window)
    dialog.reference_combo.setCurrentText("wide.fits")
    dialog.new_combo.setCurrentText("narrow.fits")
    dialog._on_measure()

    assert dialog._last_result is None
    assert "anchos distintos" in dialog.result_label.text()


def test_flexure_correction_menu_action_requires_two_windows(qapp, main_window):
    data = _arc_image()
    main_window.add_image_window(data, "only_one.fits")
    qapp.processEvents()

    main_window._open_flexure_correction_dialog()

    assert "dos ventanas" in main_window.statusBar().currentMessage().lower()
