"""Pruebas de humo del demosaico OSC y de la caché local de catálogos en
la GUI real: el proceso "Demosaico de mosaico de color" del taller sobre
un mosaico Bayer real, y el diálogo de descarga del catálogo del campo.

Requiere PySide6 y un display X -- se salta si no están disponibles."""
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


def _bayer_mosaic(shape=(40, 40), pattern="RGGB") -> np.ndarray:
    rng = np.random.default_rng(3)
    scene = np.full(shape, 1000.0)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    scene += 8000.0 * np.exp(-(((xx - 20) ** 2 + (yy - 20) ** 2) / (2 * 2.0**2)))
    scene += rng.normal(0.0, 10.0, shape)
    response = {"R": 0.55, "G": 1.0, "B": 0.45}
    mosaic = np.zeros(shape)
    for index, channel in enumerate(pattern):
        row, col = index // 2, index % 2
        mosaic[row::2, col::2] = scene[row::2, col::2] * response[channel]
    return mosaic


def test_debayer_process_is_registered_and_wired(qapp):
    from qt_app.processes.registry import build_process_registry

    registry = build_process_registry()
    process = next((p for p in registry if p.process_id == "imtools.debayer"), None)
    assert process is not None, "el demosaico debe estar en el explorador de procesos"
    assert process.is_wired, "debe estar cableado a una función real, no listado sin implementar"
    parameter_names = {spec.name for spec in process.parameters}
    assert parameter_names == {"method", "pattern"}


def test_debayer_process_runs_on_a_real_mosaic_using_the_header_pattern(qapp):
    from qt_app.processes.registry import build_process_registry

    process = next(p for p in build_process_registry() if p.process_id == "imtools.debayer")
    data = _bayer_mosaic()

    result = process.run(data, {"method": "luminancia", "pattern": "auto", "_header": {"BAYERPAT": "RGGB"}})

    assert result.output_data is not None
    assert result.output_data.shape == (20, 20), "SuperPixel/luminancia binifica 2x2"
    assert "RGGB" in result.summary
    assert "DUPLICA" in result.summary, "debe avisar de que la escala de píxel cambia"


def test_debayer_process_refuses_to_guess_a_pattern_without_the_header(qapp):
    """Nunca asumir 'RGGB porque es lo más común': con una cámara
    distinta daría colores y fotometría incorrectos en silencio."""
    from qt_app.processes.registry import build_process_registry

    process = next(p for p in build_process_registry() if p.process_id == "imtools.debayer")

    with pytest.raises(ValueError, match="no declara BAYERPAT"):
        process.run(_bayer_mosaic(), {"method": "luminancia", "pattern": "auto", "_header": {}})


def test_debayer_process_accepts_an_explicit_pattern_without_header(qapp):
    from qt_app.processes.registry import build_process_registry

    process = next(p for p in build_process_registry() if p.process_id == "imtools.debayer")
    result = process.run(_bayer_mosaic(), {"method": "superpixel", "pattern": "RGGB", "_header": {}})

    assert result.output_data.shape == (20, 20, 3)
    assert "elegido a mano" in result.summary


def test_bilinear_method_warns_that_values_are_interpolated(qapp):
    from qt_app.processes.registry import build_process_registry

    process = next(p for p in build_process_registry() if p.process_id == "imtools.debayer")
    result = process.run(_bayer_mosaic(), {"method": "bilineal", "pattern": "RGGB", "_header": {}})

    assert result.output_data.shape == (40, 40, 3), "bilineal conserva la resolución completa"
    assert "INTERPOLADOS" in result.summary, "debe advertir de que no vale para fotometría"


def test_catalog_cache_dialog_prefills_the_field_from_a_real_wcs(qapp, tmp_path, monkeypatch):
    from astropy.wcs import WCS

    import astrophysics_suite.catalogs.local_cache as local_cache_module
    from qt_app.catalogs.catalog_cache_dialog import CatalogCacheDialog

    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [50.0, 50.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [10.9131, 41.2120]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    dialog = CatalogCacheDialog(wcs, (100, 100), "M 31")

    assert dialog.ra_spin.value() == pytest.approx(10.9131, abs=1e-2)
    assert dialog.dec_spin.value() == pytest.approx(41.2120, abs=1e-2)
    assert dialog.radius_spin.value() > 0.0, "el radio debe cubrir el campo real, no quedarse a cero"
    assert dialog.object_name_edit.text() == "M 31"
    dialog.deleteLater()


def test_catalog_cache_dialog_reports_an_honest_failure_when_gaia_is_down(qapp, tmp_path, monkeypatch):
    import astrophysics_suite.catalogs.gaia as gaia_module
    import astrophysics_suite.catalogs.local_cache as local_cache_module
    from astrophysics_suite.catalogs.local_cache import CatalogCache
    from qt_app.catalogs.catalog_cache_dialog import CatalogCacheDialog

    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)
    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", lambda *a, **k: [])
    monkeypatch.setattr(gaia_module, "last_gaia_availability", lambda: (False, "Error 403: Host not in allowlist"))

    dialog = CatalogCacheDialog(None, None, "M 31")
    dialog.cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    dialog.ra_spin.setValue(10.9131)
    dialog.dec_spin.setValue(41.2120)

    from astrophysics_suite.catalogs.local_cache import download_field_to_cache

    ok, detail = download_field_to_cache(10.9131, 41.2120, 1800.0, cache=dialog.cache)
    dialog._on_download_finished((ok, detail))

    assert "403" in dialog.status_label.text()
    assert dialog.cache.regions() == [], "una descarga fallida nunca debe dejar una región fantasma"
    dialog.deleteLater()


def test_catalog_cache_dialog_shows_the_real_cache_state_after_a_download(qapp, tmp_path, monkeypatch):
    import astrophysics_suite.catalogs.local_cache as local_cache_module
    from astrophysics_suite.catalogs.local_cache import CatalogCache
    from qt_app.catalogs.catalog_cache_dialog import CatalogCacheDialog

    monkeypatch.setattr(local_cache_module, "DEFAULT_CACHE_DIR", tmp_path)

    dialog = CatalogCacheDialog(None, None, "")
    dialog.cache = CatalogCache("gaia", path=tmp_path / "gaia.sqlite3")
    dialog.cache.store_region(10.0, 41.0, 3600.0, mag_limit=20.0, rows=[
        {"source_id": "GAIA-1", "ra_deg": 10.0, "dec_deg": 41.0, "mag_g": 15.0},
    ])
    dialog._on_download_finished((True, "Descargadas y guardadas 1 fuentes"))

    assert "1 fuentes en total" in dialog.cache_state_label.text()

    dialog._on_clear()
    assert "Sin datos descargados" in dialog.cache_state_label.text()
    dialog.deleteLater()


def test_main_window_exposes_the_catalog_cache_action(qapp):
    from qt_app.main_window import MainWindow

    window = MainWindow()
    try:
        assert window.catalog_cache_action is not None
        assert "sin red" in window.catalog_cache_action.text()
        assert window.catalog_cache_action in window.astrometry_menu.actions()
    finally:
        window.close()
        window.deleteLater()
