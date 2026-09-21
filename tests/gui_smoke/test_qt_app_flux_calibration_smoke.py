"""Prueba de humo de extremo a extremo de la calibración de flujo
absoluta (menú Espectroscopía -> "Calibración de flujo absoluta..."):
función de sensibilidad real desde un espectro de estrella estándar
sintético + un archivo CALSPEC-como real, aplicada a un espectro
científico y guardada como FITS real.

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


def _write_fake_calspec_file(path, wavelength):
    from astropy.io import fits

    # Ley de potencias suave y conocida -- una estrella estándar real no
    # es plana, así que una función de sensibilidad no trivial es un
    # caso de prueba más real que un flujo de referencia constante.
    flux = 1e-13 * (wavelength / 5000.0) ** -2.0
    columns = [
        fits.Column(name="WAVELENGTH", format="D", unit="ANGSTROMS", array=wavelength),
        fits.Column(name="FLUX", format="D", unit="FLAM", array=flux),
    ]
    table_hdu = fits.BinTableHDU.from_columns(columns, name="SPECTRUM")
    primary = fits.PrimaryHDU()
    primary.header["OBJECT"] = "FAKE-STD"
    fits.HDUList([primary, table_hdu]).writeto(path, overwrite=True)
    return flux


def _instrument_response(wavelength):
    """Respuesta instrumental sintética conocida (cuentas por unidad de
    flujo físico) -- para poder verificar que calibrar y volver a medir
    con la MISMA respuesta recupera el flujo de referencia real."""
    return 5000.0 * np.exp(-((wavelength - 5500.0) / 2000.0) ** 2)


def test_flux_calibration_dialog_recovers_a_known_reference_flux(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.flux_calibration_dialog import FluxCalibrationDialog

    wavelength = np.linspace(4000.0, 7000.0, 2000)
    reference_flux = _write_fake_calspec_file(tmp_path / "std_ref.fits", wavelength)
    response = _instrument_response(wavelength)
    exptime = 60.0
    standard_counts = reference_flux * response * exptime  # cuentas reales = flujo * respuesta * tiempo

    height, width = 21, wavelength.size
    standard_data = np.tile(standard_counts, (height, 1))
    standard_header = {"EXPTIME": exptime, "AIRMASS": 1.2}
    standard_sub = main_window.add_image_window(standard_data, "std_star.fits", header=standard_header)

    science_counts = reference_flux * response * exptime  # misma estrella real, sirve como "ciencia" de prueba
    science_data = np.tile(science_counts, (height, 1))
    science_header = {"EXPTIME": exptime, "AIRMASS": 1.2, "OBJECT": "prueba"}
    science_sub = main_window.add_image_window(science_data, "science.fits", header=science_header)
    qapp.processEvents()

    solution = fit_wavelength_solution([0.0, float(width - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1)
    standard_view = standard_sub.widget()
    standard_view.fitted_wavelength_solution = solution
    science_view = science_sub.widget()
    science_view.fitted_wavelength_solution = solution
    from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord

    science_view.wavelength_calibration_record = WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=2, lamp_name="Ne"
    )

    views = {"std_star.fits": standard_view, "science.fits": science_view}
    dialog = FluxCalibrationDialog(views, main_window)
    dialog.standard_combo.setCurrentText("std_star.fits")
    dialog.science_combo.setCurrentText("science.fits")

    from PySide6.QtWidgets import QFileDialog

    reference_path = str(tmp_path / "std_ref.fits")
    original_get_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (reference_path, ""))
    try:
        dialog._on_load_reference()
    finally:
        QFileDialog.getOpenFileName = original_get_open

    assert dialog._reference_wavelength is not None
    assert dialog.airmass_spin.value() == pytest.approx(1.2)  # tomada de la cabecera real

    dialog._on_fit_sensitivity()
    assert dialog._sensitivity is not None
    assert dialog.table.rowCount() > 0

    out_path = tmp_path / "science_fluxcal.fits"
    original_get_save = QFileDialog.getSaveFileName
    QFileDialog.getSaveFileName = staticmethod(lambda *a, **k: (str(out_path), ""))
    try:
        dialog._on_save()
    finally:
        QFileDialog.getSaveFileName = original_get_save

    assert out_path.exists()
    from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits

    wavelength_out, flux_out, header_out = load_spectrum1d_fits(str(out_path))
    assert header_out["BUNIT"] == "erg/s/cm2/Angstrom"
    assert header_out["FLUXCAL"] == "STANDARD_STAR"
    # la misma estrella real usada como ciencia: el flujo recuperado debe
    # acercarse al de referencia real donde la respuesta instrumental no
    # es despreciable (bordes del rango con respuesta ~0 son ruidosos)
    core = (wavelength_out > 4500.0) & (wavelength_out < 6500.0)
    reference_on_output_grid = np.interp(wavelength_out, wavelength, reference_flux)
    relative_error = np.abs(flux_out[core] - reference_on_output_grid[core]) / reference_on_output_grid[core]
    assert np.median(relative_error) < 0.1


def test_flux_calibration_dialog_requires_real_exptime(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.flux_calibration_dialog import FluxCalibrationDialog

    wavelength = np.linspace(4000.0, 7000.0, 500)
    reference_flux = _write_fake_calspec_file(tmp_path / "std_ref2.fits", wavelength)
    data = np.tile(reference_flux, (21, 1))
    sub = main_window.add_image_window(data, "no_exptime.fits")  # sin header EXPTIME
    qapp.processEvents()
    view = sub.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(wavelength.size - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    views = {"no_exptime.fits": view, "other.fits": view}
    dialog = FluxCalibrationDialog(views, main_window)
    dialog.standard_combo.setCurrentText("no_exptime.fits")

    from PySide6.QtWidgets import QFileDialog

    reference_path = str(tmp_path / "std_ref2.fits")
    original_get_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *a, **k: (reference_path, ""))
    try:
        dialog._on_load_reference()
    finally:
        QFileDialog.getOpenFileName = original_get_open

    dialog._on_fit_sensitivity()

    assert dialog._sensitivity is None
    assert "exptime" in dialog.status_label.text().lower()


def test_flux_calibration_dialog_without_reference_warns_instead_of_crashing(qapp, main_window):
    from qt_app.spectroscopy.flux_calibration_dialog import FluxCalibrationDialog

    data = np.full((21, 200), 100.0)
    sub = main_window.add_image_window(data, "plain.fits")
    qapp.processEvents()
    view = sub.widget()

    views = {"plain.fits": view, "plain2.fits": view}
    dialog = FluxCalibrationDialog(views, main_window)
    dialog._on_fit_sensitivity()

    assert "referencia" in dialog.status_label.text().lower()
