"""Prueba de humo de extremo a extremo del bloque de astrometría (Fase
13): ajuste real de WCS a partir de estrellas marcadas a clic + tabla de
coordenadas, y registro real entre dos imágenes reproyectando por WCS
compartido -- ambos motores existían desde la Fase 9.4 sin ningún camino
de uso en la GUI, esta fase los cablea.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from astropy.wcs import WCS  # noqa: E402
from PySide6.QtCore import Qt, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QMessageBox  # noqa: E402


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


def _make_wcs(crpix=(30.0, 30.0), crval=(150.0, 2.0), scale_arcsec=1.0) -> WCS:
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = list(crpix)
    wcs.wcs.cdelt = [-scale_arcsec / 3600.0, scale_arcsec / 3600.0]
    wcs.wcs.crval = list(crval)
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    return wcs


def test_wcs_fit_flow_via_click_and_table_fits_known_solution(qapp, main_window, monkeypatch):
    from qt_app.astrometry.wcs_fit_dialog import WCSFitDialog

    # Ajustar un WCS a mano ofrece ahora guardar la copia FITS,
    # igual que las dos resoluciones automáticas: aquí interesa el
    # ajuste, no el guardado (ver `test_qt_app_wcs_fits_copy_smoke.py`).
    monkeypatch.setattr(
        "qt_app.main_window.QMessageBox.question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.No),
    )

    shape = (60, 60)
    data = np.full(shape, 100.0)
    sub_window = main_window.add_image_window(data, "wcs_fit_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    true_wcs = _make_wcs(crpix=(30.5, 30.5))  # FITS 1-indexada -> 0-indexada (29.5, 29.5)
    star_pixels = [(10.0, 10.0), (45.0, 15.0), (25.0, 50.0), (5.0, 40.0)]

    main_window._open_wcs_fit_flow()
    qapp.processEvents()
    assert view._picking is True

    for x, y in star_pixels:
        _click(view, x, y, Qt.MouseButton.LeftButton)
    qapp.processEvents()

    captured_dialog = {}
    original_exec = WCSFitDialog.exec

    def _capture_and_fill(self):
        captured_dialog["dialog"] = self
        for row, (x, y) in enumerate(star_pixels):
            # origin=0: x,y ya son 0-indexadas (misma convención que los
            # puntos marcados a clic), no hace falta ajustar a la FITS 1-indexada
            ra, dec = true_wcs.celestial.all_pix2world(x, y, 0)
            self.table.item(row, 2).setText(f"{float(ra):.8f}")
            self.table.item(row, 3).setText(f"{float(dec):.8f}")
        self._on_fit()
        return WCSFitDialog.DialogCode.Accepted

    WCSFitDialog.exec = _capture_and_fill
    try:
        _click(view, 0.0, 0.0, Qt.MouseButton.RightButton)  # termina la selección -> abre el diálogo
        qapp.processEvents()
    finally:
        WCSFitDialog.exec = original_exec

    assert view._picking is False
    assert view.fitted_wcs_solution is not None
    assert view.fitted_wcs_solution.rms_residual_arcsec < 1e-3  # datos sintéticos sin ruido
    assert view.fitted_wcs_solution.n_stars == len(star_pixels)


def test_registration_dialog_reprojects_between_two_windows_with_wcs(qapp, main_window):
    from qt_app.astrometry.registration_dialog import RegistrationDialog

    shape = (50, 50)
    yy, xx = np.mgrid[0:shape[0], 0:shape[1]]
    reference_data = 100.0 + 5000.0 * np.exp(-(((xx - 25) ** 2 + (yy - 25) ** 2)) / (2 * 3.0**2))

    reference_wcs = _make_wcs(crpix=(25.5, 25.5))
    # la misma imagen, desplazada 4 px en x -- simula una segunda toma del mismo campo.
    # np.roll(A, 4, axis=1)[i, j] = A[i, j - 4], así que la fuente que
    # estaba en la columna 25 de la referencia aparece en la columna 29
    # del target -- el CRPIX del target debe desplazarse +4 (misma
    # convención, mismo CRVAL/escala) para que ambos WCS sigan
    # describiendo el mismo cielo en la posición de la fuente.
    target_data = np.roll(reference_data, shift=4, axis=1)
    target_wcs = _make_wcs(crpix=(29.5, 25.5))

    main_window.add_image_window(reference_data, "reference.fits", wcs=reference_wcs)
    main_window.add_image_window(target_data, "target.fits", wcs=target_wcs)
    qapp.processEvents()

    views = main_window._image_views_by_title()
    assert set(views) == {"reference.fits", "target.fits"}

    dialog = RegistrationDialog(views, "reference.fits", main_window)
    received = {}
    dialog.computed.connect(lambda outcome: (received.update(outcome=outcome), main_window.add_image_window(outcome.data, outcome.title)))
    dialog.reference_combo.setCurrentText("reference.fits")
    dialog.target_combo.setCurrentText("target.fits")

    import time

    windows_before = len(main_window.mdi.subWindowList())
    dialog._on_apply()

    deadline = time.monotonic() + 10.0
    while dialog._worker is not None and dialog._worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert dialog.status_label.text() == ""
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    aligned_view = main_window.mdi.subWindowList()[-1].widget()
    # tras reproyectar, la estrella debe volver a estar cerca de (25, 25),
    # no en su posición desplazada -- confirma que la reproyección real corrigió el corrimiento
    aligned_peak = np.unravel_index(np.argmax(aligned_view.data), aligned_view.data.shape)
    np.testing.assert_allclose(aligned_peak, (25, 25), atol=1)

    outcome = received["outcome"]
    assert outcome.record.reference_title == "reference.fits"
    assert outcome.record.target_title == "target.fits"
    assert outcome.record.reference_wcs is not None  # el WCS heredado es real, no None


def test_registration_dialog_offers_to_save_the_reprojected_result_with_real_wcs(qapp, main_window, tmp_path, monkeypatch):
    """Hallazgo real cerrado (informe 91): "Registrar por WCS
    compartido..." nunca ofrecía guardar su resultado -- a diferencia de
    las cuatro resoluciones de WCS del mismo menú."""
    from astropy.io import fits
    from PySide6.QtWidgets import QFileDialog, QMessageBox

    from qt_app.astrometry.registration_dialog import RegistrationDialog

    shape = (40, 40)
    reference_data = np.full(shape, 100.0)
    reference_wcs = _make_wcs(crpix=(20.5, 20.5))
    target_data = np.full(shape, 200.0)
    target_wcs = _make_wcs(crpix=(20.5, 20.5))

    main_window.add_image_window(reference_data, "ref_save.fits", wcs=reference_wcs)
    main_window.add_image_window(target_data, "target_save.fits", wcs=target_wcs)
    qapp.processEvents()
    views = main_window._image_views_by_title()

    dialog = RegistrationDialog(views, "ref_save.fits", main_window)
    dialog.reference_combo.setCurrentText("ref_save.fits")
    dialog.target_combo.setCurrentText("target_save.fits")
    dialog.computed.connect(lambda outcome: main_window._on_registration_computed(outcome, views))

    out_path = tmp_path / "registrada.fits"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))

    import time

    dialog._on_apply()
    deadline = time.monotonic() + 10.0
    while dialog._worker is not None and dialog._worker.isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert out_path.exists()
    with fits.open(out_path) as hdul:
        assert hdul[0].header["APSREG"] is True
        assert hdul[0].header["CRVAL1"] == pytest.approx(150.0)  # el WCS de la referencia, real


def test_registration_dialog_reports_missing_wcs(qapp, main_window):
    from qt_app.astrometry.registration_dialog import RegistrationDialog

    main_window.add_image_window(np.full((10, 10), 1.0), "no_wcs_a.fits")
    main_window.add_image_window(np.full((10, 10), 1.0), "no_wcs_b.fits")
    qapp.processEvents()

    views = main_window._image_views_by_title()
    dialog = RegistrationDialog(views, "no_wcs_a.fits", main_window)
    dialog.reference_combo.setCurrentText("no_wcs_a.fits")
    dialog.target_combo.setCurrentText("no_wcs_b.fits")

    dialog._on_apply()

    assert "WCS" in dialog.status_label.text()
    assert dialog._worker is None


def test_astrometry_menu_actions_warn_without_enough_state(qapp, main_window):
    main_window._open_wcs_fit_flow()  # sin imagen activa
    assert "imagen" in main_window.statusBar().currentMessage().lower()

    main_window.add_image_window(np.full((5, 5), 1.0), "only_one.fits")
    qapp.processEvents()
    main_window._open_registration_dialog()  # una sola imagen abierta
    assert "dos imágenes" in main_window.statusBar().currentMessage()
