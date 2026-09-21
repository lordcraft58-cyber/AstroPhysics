"""Prueba de humo de extremo a extremo del nombre de producto estándar
(§37) y el historial de procesamiento en JSON (§36/§39): "Guardar
espectro calibrado (FITS)..." usa el `OBJECT` real de la cabecera como
nombre por defecto, y deja junto al producto un `.history.json` con la
cadena real de procesos que se aplicaron sobre esa vista -- que crece
(nunca se sobrescribe) si se vuelve a guardar el mismo producto.

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


def test_save_calibrated_spectrum_uses_the_real_object_name_and_writes_a_growing_history(qapp, main_window, monkeypatch, tmp_path):
    from astrophysics_suite.spectroscopy.processing_history import load_processing_history
    from astrophysics_suite.spectroscopy.spectrum1d_io import processing_history_path_for_product
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(
        data, "arc_for_history.fits", header={"OBJECT": "Vega"}, source_path=str(tmp_path / "arc_for_history.fits"),
    )
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    def _fill_and_fit(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText(str(_TRUE_WAVELENGTHS[row]))
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    original_exec = WavelengthFitDialog.exec
    WavelengthFitDialog.exec = _fill_and_fit
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    view = sub_window.widget()
    assert view.wavelength_calibration_record is not None
    assert len(view.processing_history) == 0  # el flujo de calibración no pasa por _on_process_finished

    default_path_holder = {}

    def _capture_default(_self, _title, default_path, _filter):
        default_path_holder["value"] = default_path
        return (default_path, "")

    monkeypatch.setattr("qt_app.main_window.QFileDialog.getSaveFileName", staticmethod(_capture_default))
    main_window._save_calibrated_spectrum_fits()

    assert default_path_holder["value"].endswith("Vega_1D.fits")
    out_path = tmp_path / "Vega_1D.fits"
    assert out_path.exists()

    history_path = processing_history_path_for_product(out_path)
    assert history_path.exists()
    first_save_history = load_processing_history(history_path)
    assert len(first_save_history) == 1
    assert first_save_history[0].process_name == "Guardar espectro calibrado (FITS)"

    # guardar el MISMO producto una segunda vez acumula (no sobrescribe) la cadena real
    main_window._save_calibrated_spectrum_fits()
    second_save_history = load_processing_history(history_path)
    assert len(second_save_history) == 2
    assert second_save_history[0] == first_save_history[0]
