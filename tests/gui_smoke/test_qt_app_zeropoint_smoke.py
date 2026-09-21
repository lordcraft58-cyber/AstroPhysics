"""Prueba de humo de extremo a extremo de la calibración fotométrica
real (Fase 12, bloque apphot): clic sobre varias estrellas de una imagen
con WCS real, consulta a Gaia (mockeada, sin red), y ajuste de punto cero
robusto -- de principio a fin con el hilo de fondo real.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import logging
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


def _make_wcs() -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [30.0, 30.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def _star_field_with_wcs(shape=(61, 61)):
    star_positions = [(20.0, 20.0, 30000.0), (40.0, 35.0, 12000.0)]
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    data = np.full(shape, 100.0)
    sigma = 2.0
    for x0, y0, flux in star_positions:
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    return data, star_positions


def test_zeropoint_process_runs_end_to_end_via_click_against_mocked_gaia(qapp, main_window, monkeypatch, caplog):
    caplog.set_level(logging.INFO)
    import qt_app.processes.registry as registry_module

    data, star_positions = _star_field_with_wcs()
    wcs = _make_wcs()

    true_zeropoint = 24.5
    gaia_rows = []
    for x0, y0, flux in star_positions:
        ra, dec = wcs.celestial.all_pix2world(x0, y0, 0)
        instrumental_mag = -2.5 * math.log10(flux)
        gaia_rows.append({"ra_deg": float(ra), "dec_deg": float(dec), "mag_g": instrumental_mag + true_zeropoint, "source_id": f"{x0}"})
    monkeypatch.setattr(registry_module, "query_gaia_neighbors", lambda ra, dec, **kwargs: gaia_rows)

    sub_window = main_window.add_image_window(data, "field_with_wcs.fits", wcs=wcs)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.wcs is wcs

    process = main_window._process_by_id["photometry.zeropoint"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("photometry.zeropoint", params)
    qapp.processEvents()
    assert view._picking is True

    for x0, y0, _ in star_positions:
        _click(view, x0, y0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert view._picking is False
    assert main_window.properties.apply_button.isEnabled()
    assert any("Punto cero" in record.message for record in caplog.records)


def test_zeropoint_process_without_wcs_fails_with_clear_message(qapp, main_window, caplog):
    caplog.set_level(logging.INFO)
    data, star_positions = _star_field_with_wcs()
    sub_window = main_window.add_image_window(data, "field_no_wcs.fits")  # sin wcs=
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.wcs is None

    process = main_window._process_by_id["photometry.zeropoint"]
    params = {p.name: p.default for p in process.parameters}
    main_window._run_process("photometry.zeropoint", params)
    qapp.processEvents()

    _click(view, 20.0, 20.0, Qt.MouseButton.LeftButton)
    _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert any("WCS" in record.message for record in caplog.records)
