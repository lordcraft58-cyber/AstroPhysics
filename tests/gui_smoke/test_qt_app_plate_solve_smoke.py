"""Prueba de humo de extremo a extremo del plate solving automático
(Fase 22): abrir una imagen con estrellas reales inyectadas, resolver de
verdad contra Gaia simulado (mockeado en el punto real de consulta),
aplicar el WCS a la ventana, y guardar una copia del FITS con el WCS
real escrito en la cabecera -- verificado reabriendo el archivo con
astropy, no solo "no lanza".

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

import astrophysics_suite.astrometry.plate_solve as plate_solve_module  # noqa: E402
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject  # noqa: E402


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


def _true_cd(scale_arcsec_px: float, rotation_deg: float) -> np.ndarray:
    scale_deg = scale_arcsec_px / 3600.0
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    return scale_deg * np.array([[cos_t, -sin_t], [sin_t, cos_t]])


def _synthetic_field_and_catalog(shape=(220, 220), *, ra0=200.0, dec0=15.0, scale=1.0, rotation_deg=8.0, n_stars=35, seed=4):
    rng = np.random.default_rng(seed)
    height, width = shape
    crpix = (width / 2.0, height / 2.0)
    cd = _true_cd(scale, rotation_deg)

    margin = 15.0
    xs = rng.uniform(margin, width - margin, n_stars)
    ys = rng.uniform(margin, height - margin, n_stars)
    dx, dy = xs - crpix[0], ys - crpix[1]
    offsets = cd @ np.vstack([dx, dy])
    ra, dec = gnomonic_deproject(offsets[0], offsets[1], ra0, dec0)

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    sigma = 1.3  # FWHM ~= 3.0 px, coincide con el fwhm_px por defecto de solve_plate
    for x0, y0 in zip(xs, ys):
        data += 25000.0 / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data += rng.normal(0, 3.0, shape)

    gaia_rows = [{"ra_deg": float(r), "dec_deg": float(d), "source_id": f"GAIA-{i}", "mag_g": 14.0} for i, (r, d) in enumerate(zip(ra, dec))]
    return data, gaia_rows, {"ra0": ra0, "dec0": dec0, "crpix": crpix}


def _radius_filtered_gaia_mock(gaia_rows):
    def query(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra_deg, dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    return query


def test_plate_solve_dialog_resolves_and_applies_wcs_to_view(qapp, main_window, monkeypatch):
    from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog

    data, gaia_rows, truth = _synthetic_field_and_catalog()
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))

    header = {"OBJCTRA": "13 20 00", "OBJCTDEC": "+15 00 00", "PIXSCALE": 1.0}
    sub_window = main_window.add_image_window(data, "plate_solve_test.fits", header=header)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.fitted_wcs_solution is None

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))

    original_exec = PlateSolveDialog.exec

    def _resolve_and_accept(self):
        assert self.ra_spin.value() == pytest.approx(200.0, abs=0.5)  # rellenado real desde OBJCTRA/OBJCTDEC
        self._on_solve()
        deadline_worker = self._worker
        while deadline_worker is not None and deadline_worker.isRunning():
            qapp.processEvents()
        qapp.processEvents()
        assert self.accept_button.isEnabled(), self.status_label.text()
        return PlateSolveDialog.DialogCode.Accepted

    PlateSolveDialog.exec = _resolve_and_accept
    try:
        main_window._open_plate_solve_dialog()
        qapp.processEvents()
    finally:
        PlateSolveDialog.exec = original_exec

    assert view.fitted_wcs_solution is not None
    true_ra, true_dec = gnomonic_deproject(np.array([0.0]), np.array([0.0]), truth["ra0"], truth["dec0"])
    solved_ra, solved_dec = view.fitted_wcs_solution.pixel_to_sky(*truth["crpix"])
    sep_arcsec = angular_separation_deg(float(true_ra[0]), float(true_dec[0]), solved_ra, solved_dec) * 3600.0
    assert sep_arcsec < 5.0
    assert main_window._last_result_table is not None


def test_plate_solve_dialog_simbad_lookup_fills_ra_dec(qapp, main_window, monkeypatch):
    """Flujo estilo "Spectrophotometric Color Calibration" de PixInsight:
    el usuario escribe el nombre real del objeto y pulsa "Buscar en
    SIMBAD...", que rellena RA/Dec -- sin tocar la red real (mockeado en
    el punto real de consulta, como el resto de tests de este archivo)."""
    import qt_app.astrometry.plate_solve_dialog as plate_solve_dialog_module
    from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog

    def fake_resolve(name):
        assert name == "M 31"
        return 10.6847083, 41.26875, "SIMBAD: M 31"

    monkeypatch.setattr(plate_solve_dialog_module, "resolve_object_coordinates", fake_resolve)

    dialog = PlateSolveDialog(np.zeros((50, 50)), {}, main_window)
    dialog.object_name_edit.setText("M 31")
    dialog._on_simbad_lookup()
    deadline_worker = dialog._simbad_worker
    while deadline_worker is not None and deadline_worker.isRunning():
        qapp.processEvents()
    qapp.processEvents()

    assert dialog.ra_spin.value() == pytest.approx(10.6847083, abs=1e-4)
    assert dialog.dec_spin.value() == pytest.approx(41.26875, abs=1e-4)
    assert "SIMBAD" in dialog.simbad_status_label.text()
    dialog.close()


def test_plate_solve_dialog_simbad_lookup_reports_failure_honestly(qapp, main_window, monkeypatch):
    import qt_app.astrometry.plate_solve_dialog as plate_solve_dialog_module
    from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog

    monkeypatch.setattr(plate_solve_dialog_module, "resolve_object_coordinates", lambda name: None)

    dialog = PlateSolveDialog(np.zeros((50, 50)), {}, main_window)
    dialog.object_name_edit.setText("Objeto inexistente xyz123")
    original_ra, original_dec = dialog.ra_spin.value(), dialog.dec_spin.value()
    dialog._on_simbad_lookup()
    deadline_worker = dialog._simbad_worker
    while deadline_worker is not None and deadline_worker.isRunning():
        qapp.processEvents()
    qapp.processEvents()

    assert "no pudo resolver" in dialog.simbad_status_label.text()
    assert dialog.ra_spin.value() == original_ra  # nunca inventa una posición
    assert dialog.dec_spin.value() == original_dec
    dialog.close()


def test_plate_solve_dialog_prefills_object_name_from_fits_object_header(qapp, main_window):
    from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog

    dialog = PlateSolveDialog(np.zeros((50, 50)), {"OBJECT": "M 42"}, main_window)
    assert dialog.object_name_edit.text() == "M 42"
    dialog.close()


def test_plate_solve_dialog_reports_failure_without_touching_view(qapp, main_window, monkeypatch):
    from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog

    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", lambda *a, **k: [])

    data = np.full((100, 100), 200.0)  # campo plano, sin estrellas que detectar
    sub_window = main_window.add_image_window(data, "plate_solve_fail_test.fits", header={})
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    original_exec = PlateSolveDialog.exec

    def _try_and_cancel(self):
        self.ra_spin.setValue(150.0)
        self.dec_spin.setValue(20.0)
        self.scale_spin.setValue(1.0)
        self._on_solve()
        deadline_worker = self._worker
        while deadline_worker is not None and deadline_worker.isRunning():
            qapp.processEvents()
        qapp.processEvents()
        assert "FALLIDO" in self.status_label.text()
        assert not self.accept_button.isEnabled()
        return PlateSolveDialog.DialogCode.Rejected

    PlateSolveDialog.exec = _try_and_cancel
    try:
        main_window._open_plate_solve_dialog()
        qapp.processEvents()
    finally:
        PlateSolveDialog.exec = original_exec

    assert view.fitted_wcs_solution is None


def test_saving_wcs_fits_copy_writes_a_real_solvable_header(qapp, main_window, monkeypatch, tmp_path):
    from astropy.io import fits
    from astropy.wcs import WCS as AstropyWCS

    from astrophysics_suite.astrometry.wcs_fit import fit_wcs

    solution = fit_wcs(
        [(10.0, 10.0), (90.0, 10.0), (10.0, 90.0), (50.0, 50.0)],
        [(120.01, 40.0), (119.99, 40.0), (120.01, 40.02), (120.0, 40.01)],
        crpix_px=(50.0, 50.0),
    )

    data = np.full((100, 100), 100.0)
    source_path = tmp_path / "original.fits"
    fits.PrimaryHDU(data.astype(np.float32)).writeto(source_path)
    sub_window = main_window.add_image_window(data, "original.fits", header={"OBJECT": "TEST"}, source_path=str(source_path))
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    out_path = tmp_path / "original_wcs.fits"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))

    main_window._offer_to_save_wcs_fits_copy(view, solution)

    assert out_path.exists()
    with fits.open(out_path) as hdul:
        assert hdul[0].header.get("OBJECT") == "TEST"  # header original preservado
        reloaded_wcs = AstropyWCS(hdul[0].header)
        assert reloaded_wcs.has_celestial
        for x0, y0 in [(50.0, 50.0), (10.0, 10.0)]:
            expected_ra, expected_dec = solution.pixel_to_sky(x0, y0)
            got_ra, got_dec = reloaded_wcs.all_pix2world(x0, y0, 0)
            assert float(got_ra) == pytest.approx(expected_ra, abs=1e-5)
            assert float(got_dec) == pytest.approx(expected_dec, abs=1e-5)
