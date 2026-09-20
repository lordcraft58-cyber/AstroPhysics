"""Prueba de humo de extremo a extremo de la calibración en longitud de
onda (Fase 15, bloque espectroscopía): detección automática real de
líneas de arco sobre la fila central de la imagen activa + tabla de
longitudes de onda conocidas + ajuste polinómico real, con exportación a
CSV a través del mismo mecanismo de la Fase 14.

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
_TRUE_WAVELENGTHS = (4046.6, 4358.3, 5460.7, 5769.6)  # líneas de mercurio reales, de referencia


def _synthetic_arc_row(width=300, height=21):
    row = np.full(width, 100.0)
    for pixel in _TRUE_PIXELS:
        idx = int(round(pixel))
        row[idx - 2 : idx + 3] += [50, 400, 1200, 400, 50]
    return np.tile(row, (height, 1))


def test_wavelength_fit_flow_detects_lines_and_fits_known_solution(qapp, main_window):
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "arc_lamp.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    captured = {}
    original_exec = WavelengthFitDialog.exec

    def _capture_and_fill(self):
        captured["dialog"] = self
        assert self.table.rowCount() == len(_TRUE_PIXELS)
        # empareja cada línea detectada con su longitud de onda conocida
        # más cercana en píxel (orden de detección = orden creciente de píxel)
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText(str(_TRUE_WAVELENGTHS[row]))
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    WavelengthFitDialog.exec = _capture_and_fill
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    assert view.fitted_wavelength_solution is not None
    assert view.fitted_wavelength_solution.rms_residual < 0.1  # datos sintéticos limpios
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == len(_TRUE_PIXELS)

    # la solución ajustada debe predecir correctamente una longitud de onda
    # intermedia real, no solo reproducir los puntos de entrada
    predicted = view.fitted_wavelength_solution.pixel_to_wavelength(110.0)
    assert predicted == pytest.approx(4358.3, abs=1.0)


def test_wavelength_fit_flow_reports_too_few_lines(qapp, main_window):
    data = np.full((21, 300), 100.0)  # sin líneas de arco -- espectro plano
    sub_window = main_window.add_image_window(data, "flat_no_lines.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    main_window._open_wavelength_fit_flow()

    assert "línea" in main_window.statusBar().currentMessage().lower()


def test_wavelength_fit_flow_without_active_image_warns(qapp, main_window):
    for sub_window in list(main_window.mdi.subWindowList()):
        sub_window.close()
    qapp.processEvents()

    main_window._open_wavelength_fit_flow()

    assert "imagen" in main_window.statusBar().currentMessage().lower()


def test_wavelength_table_exports_to_real_csv(qapp, main_window, monkeypatch, tmp_path):
    import qt_app.main_window as main_window_module
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog
    from astrophysics_suite.tables.table import Table

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "arc_export_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    def _capture_and_fill(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText(str(_TRUE_WAVELENGTHS[row]))
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    original_exec = WavelengthFitDialog.exec
    WavelengthFitDialog.exec = _capture_and_fill
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    out_path = tmp_path / "wavelength_lines.csv"
    monkeypatch.setattr(main_window_module.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))
    main_window._export_last_table()

    assert out_path.exists()
    reloaded = Table.from_csv(str(out_path))
    assert len(reloaded.rows) == len(_TRUE_PIXELS)
    assert "wavelength" in reloaded.columns


def _synthetic_ne_arc_row(width=1600, height=21, wavelength_at_pixel0=5700.0, dispersion=1.4, seed=3):
    """Fila de arco sintética con líneas Ne REALES del catálogo público
    (no inventadas), en su posición de píxel exacta bajo la dispersión
    dada -- para probar la sugerencia automática contra el catálogo."""
    from astrophysics_suite.spectroscopy.line_catalog import NEON_ARC_LINES

    rng = np.random.default_rng(seed)
    row = np.full(width, 100.0) + rng.normal(0, 2.0, width)
    injected = []
    for line in NEON_ARC_LINES:
        pixel = (line.wavelength_air_angstrom - wavelength_at_pixel0) / dispersion
        if 10 < pixel < width - 10:
            idx = int(round(pixel))
            row[idx - 2 : idx + 3] += np.array([80, 600, 1500, 600, 80])
            injected.append((pixel, line))
    return np.tile(row, (height, 1)), injected


def test_wavelength_fit_dialog_suggests_real_catalog_matches_before_confirmation(qapp, main_window):
    """§10: la sugerencia rellena la tabla, pero no aplica nada por sí
    sola -- sigue haciendo falta pulsar "Ajustar solución"."""
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog

    data, injected = _synthetic_ne_arc_row()
    assert len(injected) >= 4
    sub_window = main_window.add_image_window(data, "ne_arc.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    captured = {}
    original_exec = WavelengthFitDialog.exec

    def _use_suggestion_then_fit(self):
        captured["dialog"] = self
        self.lamp_combo.setCurrentText("Ne")
        self.dispersion_spin.setValue(1.4)
        self.zero_point_spin.setValue(5700.0)
        self._on_suggest()
        # cada celda de longitud de onda debe llevar ya una sugerencia real
        for row in range(self.table.rowCount()):
            text = self.table.item(row, 2).text()
            assert text, f"fila {row} sin sugerencia"
            assert float(text) > 0
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    WavelengthFitDialog.exec = _use_suggestion_then_fit
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    view = sub_window.widget()
    assert view.fitted_wavelength_solution is not None
    assert view.wavelength_calibration_record is not None
    assert view.wavelength_calibration_record.lamp_name == "Ne"
    assert view.wavelength_calibration_record.source.value == "lamp_real"
    # la solucion recuperada debe acercarse a la dispersion real inyectada
    predicted_a = view.fitted_wavelength_solution.pixel_to_wavelength(100.0)
    predicted_b = view.fitted_wavelength_solution.pixel_to_wavelength(200.0)
    assert (predicted_b - predicted_a) == pytest.approx(1.4 * 100, abs=0.5)


def test_save_calibrated_spectrum_writes_a_real_fits_with_the_true_wcs(qapp, main_window, monkeypatch, tmp_path):
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "arc_for_save.fits", source_path=str(tmp_path / "arc_for_save.fits"))
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    def _capture_and_fill(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText(str(_TRUE_WAVELENGTHS[row]))
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    original_exec = WavelengthFitDialog.exec
    WavelengthFitDialog.exec = _capture_and_fill
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    out_path = tmp_path / "arc_calibrated_1D.fits"
    monkeypatch.setattr("qt_app.main_window.QFileDialog.getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))
    main_window._save_calibrated_spectrum_fits()

    assert out_path.exists()
    from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits

    wavelength, flux, header = load_spectrum1d_fits(str(out_path))
    assert header["CALTYPE"] == "REAL"
    assert flux.shape == (300,)
    # el WCS releido predice lo mismo que la solucion en memoria
    view = sub_window.widget()
    expected = view.fitted_wavelength_solution.pixel_to_wavelength(np.arange(300))
    np.testing.assert_allclose(wavelength, expected, atol=1e-3)


def test_save_calibrated_spectrum_without_a_calibration_warns_instead_of_crashing(qapp, main_window):
    data = np.full((21, 300), 100.0)
    sub_window = main_window.add_image_window(data, "no_calibration_yet.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    main_window._save_calibrated_spectrum_fits()

    assert "calibra" in main_window.statusBar().currentMessage().lower()
