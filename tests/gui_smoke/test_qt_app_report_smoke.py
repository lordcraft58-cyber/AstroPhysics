"""Prueba de humo del botón "Generar informe científico..." del detalle
de candidato: ejecuta un análisis de Descubrimiento real, abre el
detalle de un candidato real y confirma que el botón produce un archivo
HTML real en disco (no solo que el diálogo se abra) -- mismo nivel de
exigencia que el resto de `tests/gui_smoke/`.

Requiere PySide6 y un display X (real o Xvfb) -- si no están disponibles,
el test se salta en vez de fallar por una razón ajena al código bajo
prueba.
"""
from __future__ import annotations

import time
from unittest import mock

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QFileDialog  # noqa: E402


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
    yield window
    window.close()


def _star_field(shape, positions, seed=3):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, 100.0, dtype=np.float32)
    for x, y in positions:
        field += 900.0 * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def _run_discovery_and_wait(qapp, main_window, target_name, images, timeout_s=10.0):
    main_window._start_discovery(target_name, images)
    deadline = time.monotonic() + timeout_s
    while main_window._discovery_job is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def test_report_button_writes_a_real_html_report_for_a_real_candidate(qapp, main_window, tmp_path, monkeypatch):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo informe", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    candidate_id = main_window.session_state.candidates[0].candidate_id
    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate_id].widget()

    report_path = tmp_path / "informe.html"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(report_path), "")))

    detail_widget._generate_report()
    qapp.processEvents()

    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert candidate_id in text
    assert "13. Revisión humana" in text
    assert "1. Observación" in text
    # Sin diálogo modal bloqueante en el éxito: la confirmación llega por
    # `report_generated` hasta la barra de estado de la ventana principal.
    assert str(report_path) in main_window.statusBar().currentMessage()


def test_report_button_shows_a_real_error_instead_of_a_fake_success(qapp, main_window, tmp_path, monkeypatch):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from qt_app.candidates import candidate_detail_widget as cdw

    field = _star_field((96, 96), [(30, 30)])
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo error informe", [(str(path), "HA")])
    assert main_window.session_state.candidates

    candidate_id = main_window.session_state.candidates[0].candidate_id
    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate_id].widget()

    # Un directorio real en vez de un archivo: `export_html` fallará de
    # verdad al intentar escribir texto sobre él (IsADirectoryError),
    # sin necesidad de simular el fallo -- igual que el test de sesión
    # corrupta usa un archivo JSON real e inválido en vez de un mock.
    directory_as_path = tmp_path / "esto_es_un_directorio"
    directory_as_path.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(directory_as_path), "")))

    with mock.patch.object(cdw.QMessageBox, "critical") as critical:
        detail_widget._generate_report()

    critical.assert_called_once()


def test_report_button_shows_real_wcs_residuals_when_the_source_image_has_a_fitted_wcs(qapp, main_window, tmp_path, monkeypatch):
    # Cierre de la brecha documentada en el cierre 44: build_candidate_
    # report ya aceptaba wcs_solution/zeropoint_fit reales, pero la GUI
    # nunca se los pasaba porque ninguno de los dos sobrevivía más allá
    # de la sesión activa. Ahora SessionState los recuerda por ruta de
    # imagen (main_window._remember_wcs_solution) y el botón los busca
    # ahí -- este test confirma la cadena completa, no solo una pieza.
    from astrophysics_suite.astrometry.wcs_fit import fit_wcs
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)
    resolved_path = str(path.resolve())
    _run_discovery_and_wait(qapp, main_window, "Campo residuales reales", [(str(path), "OIII")])
    assert main_window.session_state.candidates
    assert main_window.session_state.observations
    observation = main_window.session_state.observations[0]
    assert observation.images[0].path == resolved_path

    view_window = main_window.add_image_window(field, "field_OIII.fits", source_path=resolved_path)
    qapp.processEvents()
    view = view_window.widget()

    solution = fit_wcs(
        [(10.0, 10.0), (90.0, 10.0), (10.0, 90.0), (50.0, 50.0), (70.0, 20.0), (20.0, 70.0)],
        [(120.01, 40.0), (119.99, 40.0), (120.01, 40.02), (120.0, 40.01), (119.995, 40.005), (120.005, 40.015)],
        crpix_px=(48.0, 48.0),
    )
    main_window._remember_wcs_solution(view, solution)
    assert main_window.session_state.wcs_solutions.get(resolved_path) is solution

    candidate_id = main_window.session_state.candidates[0].candidate_id
    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate_id].widget()

    report_path = tmp_path / "informe_con_wcs.html"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(report_path), "")))

    detail_widget._generate_report()
    qapp.processEvents()

    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert "RMS del ajuste WCS" in text
    assert f"{solution.rms_residual_arcsec:.4f}" in text
    assert "NO DISPONIBLE (resultado por imagen" not in text
