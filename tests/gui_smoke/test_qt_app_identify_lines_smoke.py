"""Prueba de humo de extremo a extremo del proceso "Identificar líneas
automáticamente" (menú de procesos -> Espectroscopía): detección real
sobre un espectro sintético con líneas de Balmer reales, contra el
catálogo real, con el aviso de solape telúrico -- sin picking (opera
sobre toda la fila central de una vez).

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import logging
import time

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


def _wait_worker(qapp, main_window, timeout=10.0):
    deadline = time.monotonic() + timeout
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


_H_ALPHA = 6562.8
_O_III = 5006.8


def _synthetic_calibrated_row(*, height=21, width=3000, seed=31):
    rng = np.random.default_rng(seed)
    wavelength = np.linspace(3800.0, 7200.0, width)
    continuum = 100.0 + 0.001 * (wavelength - 5500.0)
    flux = continuum.copy()
    flux -= 15.0 * np.exp(-((wavelength - _H_ALPHA) ** 2) / (2 * 1.3**2))  # H-alpha en absorcion
    flux += 8.0 * np.exp(-((wavelength - _O_III) ** 2) / (2 * 1.0**2))  # [O III] en emision
    flux = flux + rng.normal(0, 0.2, width)
    row = np.tile(flux, (height, 1))
    return row, wavelength


def test_identify_lines_process_finds_real_lines_against_the_catalog(qapp, main_window):
    from astrophysics_suite.spectroscopy.line_catalog import LineType, SpectralLine
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

    data, wavelength = _synthetic_calibrated_row()
    sub_window = main_window.add_image_window(data, "identify_lines_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    # catálogo mínimo de prueba (no dependemos de que STELLAR_NEBULAR_LINES
    # tenga exactamente estas dos líneas con este tipo de línea)
    from qt_app.processes import registry as registry_module

    registry_module._OBJECT_LINE_CATALOGS["prueba H-alpha + O III"] = (
        SpectralLine(_H_ALPHA, "H-alpha", "H", line_type=LineType.ABSORPTION),
        SpectralLine(_O_III, "[O III]", "O", "III", line_type=LineType.EMISSION),
    )

    process = main_window._process_by_id["spectroscopy.identify_lines"]
    params = {p.name: p.default for p in process.parameters}
    params["catalog"] = "prueba H-alpha + O III"
    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("spectroscopy.identify_lines", params)
    _wait_worker(qapp, main_window)

    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 2
    labels = {row[0] for row in main_window._last_result_table.rows}
    assert labels == {"H-alpha", "[O III]"}

    spectrum_view = main_window.mdi.subWindowList()[-1].widget()
    assert len(spectrum_view._data.markers) == 2


def test_identify_lines_process_without_calibration_fails_with_a_clear_message(qapp, main_window, caplog):
    caplog.set_level(logging.INFO)
    data, _wavelength = _synthetic_calibrated_row()
    sub_window = main_window.add_image_window(data, "identify_lines_no_calibration.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.fitted_wavelength_solution is None

    process = main_window._process_by_id["spectroscopy.identify_lines"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("spectroscopy.identify_lines", params)
    _wait_worker(qapp, main_window)

    assert any("calibra" in record.message.lower() for record in caplog.records)


def test_identify_lines_process_reports_zero_matches_honestly(qapp, main_window):
    from astrophysics_suite.spectroscopy.line_catalog import LineType, SpectralLine
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution

    data, wavelength = _synthetic_calibrated_row()
    sub_window = main_window.add_image_window(data, "identify_lines_no_match.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(
        [0.0, float(data.shape[1] - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    from qt_app.processes import registry as registry_module

    registry_module._OBJECT_LINE_CATALOGS["prueba lejos de todo"] = (
        SpectralLine(4000.0, "nada real aquí", "X", line_type=LineType.ABSORPTION),
    )

    process = main_window._process_by_id["spectroscopy.identify_lines"]
    params = {p.name: p.default for p in process.parameters}
    params["catalog"] = "prueba lejos de todo"
    main_window._run_process("spectroscopy.identify_lines", params)
    _wait_worker(qapp, main_window)

    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 0
