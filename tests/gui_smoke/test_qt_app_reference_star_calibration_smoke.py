"""Prueba de humo de extremo a extremo de la calibración en longitud de
onda por estrella de referencia (§13): sin lámpara real disponible, el
taller infiere una calibración PROVISIONAL a partir de líneas de Balmer
reales de una estrella sintética, y la deja aplicada sobre la ventana
(`view.fitted_wavelength_solution`) exactamente igual que "Calibrar
longitud de onda...".

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

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


def _wait_active_worker(qapp, main_window, timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def _synthetic_reference_star_row(*, true_wave0=4000.0, true_dispersion=2.0, width=2000, height=21, seed=17):
    from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES

    rng = np.random.default_rng(seed)
    pixel = np.arange(width, dtype=np.float64)
    flux = np.full(width, 200.0)
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - true_wave0) / true_dispersion
        if 0 <= true_pixel < width:
            flux -= 40.0 * np.exp(-((pixel - true_pixel) ** 2) / (2 * 2.5**2))
    flux += rng.normal(0, 0.3, width)
    return np.tile(flux, (height, 1))


def test_reference_star_calibration_process_applies_a_real_provisional_solution_to_the_view(qapp, main_window):
    true_wave0, true_dispersion = 4000.0, 2.0
    data = _synthetic_reference_star_row(true_wave0=true_wave0, true_dispersion=true_dispersion)
    sub_window = main_window.add_image_window(data, "reference_star_calibration.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.header = {"OBJECT": "Vega (sintética)"}
    assert view.fitted_wavelength_solution is None

    process = main_window._process_by_id["spectroscopy.reference_star_calibration"]
    params = {p.name: p.default for p in process.parameters}
    params["approx_dispersion_angstrom_per_px"] = true_dispersion * 1.01
    params["approx_wavelength_at_pixel0"] = true_wave0 + 10.0
    params["tolerance_angstrom"] = 40.0
    main_window._run_process("spectroscopy.reference_star_calibration", params)
    _wait_active_worker(qapp, main_window)

    assert view.fitted_wavelength_solution is not None
    assert view.fitted_wavelength_solution.pixel_to_wavelength(0.0) == pytest.approx(true_wave0, abs=5.0)
    assert view.wavelength_calibration_record is not None
    assert view.wavelength_calibration_record.source.value == "reference_star"
    assert view.wavelength_calibration_record.reference_object == "Vega (sintética)"
    assert view.wavelength_calibration_spectrum is not None
