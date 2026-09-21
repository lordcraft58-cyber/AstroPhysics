"""Prueba de humo de extremo a extremo del plate solving CIEGO (cierre
del motor de resolución astrométrica automática): abrir una imagen SIN
WCS y SIN puntero, resolver de verdad emparejando asterismos contra una
caché local real (poblada en un directorio temporal, como lo haría una
descarga previa), aplicar el WCS a la ventana, y guardar una copia del
FITS con el WCS real escrito en la cabecera -- verificado reabriendo el
archivo con astropy, mismo rigor que `test_qt_app_plate_solve_smoke.py`
para el camino con puntero.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox  # noqa: E402

import astrophysics_suite.astrometry.plate_solve as plate_solve_module  # noqa: E402
import astrophysics_suite.catalogs.local_cache as local_cache_module  # noqa: E402
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject, gnomonic_project  # noqa: E402
from astrophysics_suite.catalogs.local_cache import CatalogCache  # noqa: E402


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


def _radius_filtered_gaia_mock(gaia_rows):
    def query(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra_deg, dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    return query


def _wide_catalog_and_image(*, ra0=83.633, dec0=-5.391, scale_arcsec_px=1.2, rotation_deg=37.0, shape=(512, 512)):
    """Mismo generador que `tests/unit/astrometry/test_blind_solve.py`:
    catálogo disperso en un campo bastante más amplio que la imagen --
    el resolutor ciego tiene que encontrar la sub-región correcta, no
    solo emparejar un recorte ya alineado."""
    rng = np.random.default_rng(42)
    xi = rng.uniform(-0.3, 0.3, 400)
    eta = rng.uniform(-0.3, 0.3, 400)
    cat_ra, cat_dec = gnomonic_deproject(xi, eta, ra0, dec0)
    mags = rng.uniform(10.0, 16.0, 400)
    catalog_rows = [
        {"source_id": f"CAT-{i}", "ra_deg": float(r), "dec_deg": float(d), "mag_g": float(m)}
        for i, (r, d, m) in enumerate(zip(cat_ra, cat_dec, mags))
    ]

    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    scale_deg = scale_arcsec_px / 3600.0
    cd = scale_deg * np.array([[cos_t, -sin_t], [sin_t, cos_t]])
    cd_inv = np.linalg.inv(cd)
    img_xi, img_eta = gnomonic_project(np.array(cat_ra), np.array(cat_dec), ra0, dec0)
    offsets = cd_inv @ np.vstack([img_xi, img_eta])
    height, width = shape
    px, py = offsets[0] + width / 2.0, offsets[1] + height / 2.0
    margin = 12.0
    in_field = (px >= margin) & (px < width - margin) & (py >= margin) & (py < height - margin)

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    for x0, y0, mag in zip(px[in_field], py[in_field], mags[in_field]):
        amplitude = 20000.0 * 10 ** (-0.4 * (mag - 10.0))
        data += amplitude * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * 1.8**2))
    data += rng.normal(0, 3.0, shape)

    truth = {"ra0": ra0, "dec0": dec0, "crpix": (width / 2.0, height / 2.0), "n_in_field": int(in_field.sum())}
    return data.astype(np.float32), catalog_rows, truth


def test_blind_plate_solve_dialog_resolves_and_applies_wcs_to_view(qapp, main_window, monkeypatch, tmp_path):
    from qt_app.astrometry.blind_solve_dialog import BlindPlateSolveDialog

    data, catalog_rows, truth = _wide_catalog_and_image()
    assert truth["n_in_field"] >= 15, "la propia prueba necesita suficientes estrellas reales en el campo"

    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(catalog_rows))
    CatalogCache("gaia").store_region(truth["ra0"], truth["dec0"], 1200.0, mag_limit=20.0, rows=catalog_rows)

    sub_window = main_window.add_image_window(data, "blind_solve_test.fits", header={})  # SIN RA/DEC ni OBJECT
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.fitted_wcs_solution is None

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))

    original_exec = BlindPlateSolveDialog.exec

    def _resolve_and_accept(self):
        assert "descargada" in self.cache_status_label.text() or "región" in self.cache_status_label.text()
        self._on_solve()
        deadline_worker = self._worker
        while deadline_worker is not None and deadline_worker.isRunning():
            qapp.processEvents()
        qapp.processEvents()
        assert self.accept_button.isEnabled(), self.status_label.text()
        return BlindPlateSolveDialog.DialogCode.Accepted

    BlindPlateSolveDialog.exec = _resolve_and_accept
    try:
        main_window._open_blind_plate_solve_dialog()
        qapp.processEvents()
    finally:
        BlindPlateSolveDialog.exec = original_exec

    assert view.fitted_wcs_solution is not None
    solved_ra, solved_dec = view.fitted_wcs_solution.pixel_to_sky(*truth["crpix"])
    sep_arcsec = angular_separation_deg(truth["ra0"], truth["dec0"], solved_ra, solved_dec) * 3600.0
    assert sep_arcsec < 5.0, f"separación real: {sep_arcsec:.2f}\""
    assert main_window._last_result_table is not None


def test_blind_plate_solve_dialog_reports_failure_without_a_local_catalog(qapp, main_window, monkeypatch, tmp_path):
    from qt_app.astrometry.blind_solve_dialog import BlindPlateSolveDialog

    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)  # caché vacía, real, sin regiones

    data, _catalog_rows, _truth = _wide_catalog_and_image()
    sub_window = main_window.add_image_window(data, "blind_solve_fail_test.fits", header={})
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    original_exec = BlindPlateSolveDialog.exec

    def _try_and_cancel(self):
        self._on_solve()
        deadline_worker = self._worker
        while deadline_worker is not None and deadline_worker.isRunning():
            qapp.processEvents()
        qapp.processEvents()
        assert "FALLIDO" in self.status_label.text()
        assert "catálogo de referencia local" in self.status_label.text()
        assert not self.accept_button.isEnabled()
        return BlindPlateSolveDialog.DialogCode.Rejected

    BlindPlateSolveDialog.exec = _try_and_cancel
    try:
        main_window._open_blind_plate_solve_dialog()
        qapp.processEvents()
    finally:
        BlindPlateSolveDialog.exec = original_exec

    assert view.fitted_wcs_solution is None


def test_saving_blind_solved_wcs_fits_copy_writes_a_real_solvable_header(qapp, main_window, monkeypatch, tmp_path):
    """Mismo test de guardado real que el camino con puntero
    (`test_qt_app_plate_solve_smoke.py::test_saving_wcs_fits_copy_writes_a_real_solvable_header`)
    -- `_offer_to_save_wcs_fits_copy` es compartido entre ambos caminos,
    esto confirma que también funciona de verdad llamado desde el flujo
    ciego, no solo que existe."""
    from astropy.io import fits
    from astropy.wcs import WCS as AstropyWCS

    from astrophysics_suite.astrometry.provenance import SOURCE_BLIND_SOLVE, WCSRecord
    from astrophysics_suite.astrometry.wcs_fit import fit_wcs

    solution = fit_wcs(
        [(10.0, 10.0), (90.0, 10.0), (10.0, 90.0), (50.0, 50.0)],
        [(120.01, 40.0), (119.99, 40.0), (120.01, 40.02), (120.0, 40.01)],
        crpix_px=(50.0, 50.0),
    )

    data = np.full((100, 100), 100.0)
    source_path = tmp_path / "original_blind.fits"
    fits.PrimaryHDU(data.astype(np.float32)).writeto(source_path)
    sub_window = main_window.add_image_window(data, "original_blind.fits", header={"OBJECT": "TEST-BLIND"}, source_path=str(source_path))
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    out_path = tmp_path / "original_blind_wcs.fits"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out_path), "")))

    main_window._offer_to_save_wcs_fits_copy(
        view, WCSRecord(solution=solution, source=SOURCE_BLIND_SOLVE, catalog="Gaia DR3 (caché local)")
    )

    assert out_path.exists()
    with fits.open(out_path) as hdul:
        assert hdul[0].header.get("OBJECT") == "TEST-BLIND"
        reloaded_wcs = AstropyWCS(hdul[0].header)
        assert reloaded_wcs.has_celestial
        for x0, y0 in [(50.0, 50.0), (10.0, 10.0)]:
            expected_ra, expected_dec = solution.pixel_to_sky(x0, y0)
            got_ra, got_dec = reloaded_wcs.all_pix2world(x0, y0, 0)
            assert float(got_ra) == pytest.approx(expected_ra, abs=1e-5)
            assert float(got_dec) == pytest.approx(expected_dec, abs=1e-5)
