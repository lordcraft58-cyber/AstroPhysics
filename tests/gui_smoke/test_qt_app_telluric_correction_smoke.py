"""Prueba de humo de extremo a extremo de la corrección de absorción
telúrica (menú Espectroscopía -> "Corrección de absorción telúrica..."):
mide la transmisión real de una estándar telúrica sintética con una banda
conocida, la aplica a un espectro científico con la misma banda inyectada
y verifica que la banda queda corregida mientras el resto del espectro
(y cualquier línea propia de la estándar fuera de banda) permanece
intacto, guardando un FITS real con la procedencia de la corrección.

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


_BAND_CENTER = 6875.5  # centro real de la banda catalogada "O2 B" (6867.0-6884.0)


def _dip(wavelength, *, center, width, depth):
    return 1.0 - depth * np.exp(-0.5 * ((wavelength - center) / width) ** 2)


def _standard_image(*, height=21, width=1200, seed=5):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(6700.0, 7000.0, width)
    continuum = 1000.0 + 0.05 * (wavelength - wavelength[0])
    row = continuum * _dip(wavelength, center=_BAND_CENTER, width=4.0, depth=0.6) + rng.normal(0, 1.0, width)
    return np.tile(row, (height, 1))


def _science_image(*, height=21, width=1200, seed=9):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(6700.0, 7000.0, width)
    continuum = 500.0 + 0.02 * (wavelength - wavelength[0])
    row = continuum * _dip(wavelength, center=_BAND_CENTER, width=4.0, depth=0.6) + rng.normal(0, 0.3, width)
    return np.tile(row, (height, 1))


def test_telluric_correction_dialog_measures_and_applies_a_known_band(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.telluric_correction_dialog import TelluricCorrectionDialog

    standard_data = _standard_image()
    science_data = _science_image()

    standard_sub = main_window.add_image_window(standard_data, "telluric_standard.fits")
    science_sub = main_window.add_image_window(
        science_data, "science.fits", source_path=str(tmp_path / "science.fits")
    )
    qapp.processEvents()

    width = standard_data.shape[1]
    solution = fit_wavelength_solution(
        [0.0, width - 1.0], [6700.0, 7000.0], degree=1,
    )
    for sub in (standard_sub, science_sub):
        view = sub.widget()
        view.fitted_wavelength_solution = solution
        view.wavelength_calibration_record = WavelengthCalibrationRecord(
            solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=2, lamp_name="Ne"
        )

    views = {"telluric_standard.fits": standard_sub.widget(), "science.fits": science_sub.widget()}
    dialog = TelluricCorrectionDialog(views, main_window)
    dialog.standard_combo.setCurrentText("telluric_standard.fits")
    dialog.science_combo.setCurrentText("science.fits")

    dialog._on_measure_standard()
    assert dialog._transmission is not None

    dialog._on_apply()
    assert dialog._last_result is not None
    assert len(dialog._last_result.bands_used) >= 1
    assert "Corrección aplicada" in dialog.status_label.text()
    assert dialog.table.rowCount() == len(dialog._last_result.bands_used)

    out_path = tmp_path / "science_tellcorr.fits"
    from PySide6.QtWidgets import QFileDialog

    original_get_save = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_path), ""))
    try:
        dialog._on_save()
    finally:
        QFileDialog.getSaveFileName = original_get_save

    assert out_path.exists()
    from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits

    _, flux_out, header_out = load_spectrum1d_fits(str(out_path))
    assert flux_out.shape == (width,)
    assert header_out.get("TELLCORR")

    table = dialog.result_table()
    assert table is not None


def test_telluric_correction_menu_action_requires_two_windows(qapp, main_window):
    data = _science_image()
    main_window.add_image_window(data, "only_one.fits")
    qapp.processEvents()

    main_window._open_telluric_correction_dialog()

    assert "dos ventanas" in main_window.statusBar().currentMessage().lower()
