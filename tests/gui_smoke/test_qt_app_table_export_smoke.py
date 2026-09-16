"""Prueba de humo de extremo a extremo de la exportación de tablas
(Fase 14): tanto "Ajustar WCS..." como `photometry.zeropoint` producen
una `Table` real, y "Herramientas -> Exportar última tabla a CSV..." la
escribe a un archivo real que se puede releer.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import math
import time

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from astropy.wcs import WCS  # noqa: E402
from PySide6.QtCore import Qt, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
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


def _click(view, scene_x: float, scene_y: float, button: Qt.MouseButton) -> None:
    view_point = view.mapFromScene(QPointF(scene_x, scene_y))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(view_point), button, button, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(event)


def test_export_last_table_warns_when_nothing_to_export(qapp, main_window):
    main_window._export_last_table()
    assert "no hay ninguna tabla" in main_window.statusBar().currentMessage().lower()


def test_zeropoint_process_result_table_exports_to_real_csv(qapp, main_window, monkeypatch, tmp_path):
    import qt_app.processes.registry as registry_module
    import qt_app.main_window as main_window_module
    from astrophysics_suite.tables.table import Table

    shape = (61, 61)
    star_positions = [(20.0, 20.0, 30000.0), (40.0, 35.0, 12000.0)]
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    data = np.full(shape, 100.0)
    sigma = 2.0
    for x0, y0, flux in star_positions:
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [30.0, 30.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    true_zeropoint = 24.5
    gaia_rows = []
    for x0, y0, flux in star_positions:
        ra, dec = wcs.celestial.all_pix2world(x0, y0, 0)
        instrumental_mag = -2.5 * math.log10(flux)
        gaia_rows.append({"ra_deg": float(ra), "dec_deg": float(dec), "mag_g": instrumental_mag + true_zeropoint, "source_id": f"{x0}"})
    monkeypatch.setattr(registry_module, "query_gaia_neighbors", lambda ra, dec, **kwargs: gaia_rows)

    sub_window = main_window.add_image_window(data, "zp_export_test.fits", wcs=wcs)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    process = main_window._process_by_id["photometry.zeropoint"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("photometry.zeropoint", params)
    qapp.processEvents()

    for x0, y0, _ in star_positions:
        _click(view, x0, y0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 2

    out_path = tmp_path / "zeropoint_stars.csv"
    monkeypatch.setattr(main_window_module.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))
    main_window._export_last_table()

    assert out_path.exists()
    reloaded = Table.from_csv(str(out_path))
    assert reloaded.columns == main_window._last_result_table.columns
    assert len(reloaded.rows) == 2


def test_wcs_fit_dialog_table_exports_to_real_csv(qapp, main_window, monkeypatch, tmp_path):
    from qt_app.astrometry.wcs_fit_dialog import WCSFitDialog
    from astrophysics_suite.tables.table import Table
    import qt_app.main_window as main_window_module

    shape = (60, 60)
    data = np.full(shape, 100.0)
    sub_window = main_window.add_image_window(data, "wcs_export_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    true_wcs = WCS(naxis=2)
    true_wcs.wcs.crpix = [30.5, 30.5]
    true_wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    true_wcs.wcs.crval = [150.0, 2.0]
    true_wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    star_pixels = [(10.0, 10.0), (45.0, 15.0), (25.0, 50.0)]

    main_window._open_wcs_fit_flow()
    qapp.processEvents()

    for x, y in star_pixels:
        _click(view, x, y, Qt.MouseButton.LeftButton)
    qapp.processEvents()

    def _capture_and_fill(self):
        for row, (x, y) in enumerate(star_pixels):
            ra, dec = true_wcs.celestial.all_pix2world(x, y, 0)
            self.table.item(row, 2).setText(f"{float(ra):.8f}")
            self.table.item(row, 3).setText(f"{float(dec):.8f}")
        self._on_fit()
        return WCSFitDialog.DialogCode.Accepted

    original_exec = WCSFitDialog.exec
    WCSFitDialog.exec = _capture_and_fill
    try:
        _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
        qapp.processEvents()
    finally:
        WCSFitDialog.exec = original_exec

    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == 3

    out_path = tmp_path / "wcs_fit_residuals.csv"
    monkeypatch.setattr(main_window_module.QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))
    main_window._export_last_table()

    assert out_path.exists()
    reloaded = Table.from_csv(str(out_path))
    assert len(reloaded.rows) == 3
    assert "residual" in reloaded.columns
