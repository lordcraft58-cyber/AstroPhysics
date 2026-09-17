"""Prueba de humo de la migración del flujo de candidatos (Fase 8,
Tkinter) al taller Qt: ejecuta un análisis de Descubrimiento real de
principio a fin (incluido el hilo de fondo de `DiscoveryJob`, sondeado
por `QTimer` en vez de `root.after`) sobre un FITS sintético real
escrito a disco, y confirma que los candidatos resultantes llegan al
`SessionState` compartido, se muestran en el panel acoplable y se pueden
revisar desde el detalle -- el mismo nivel de exigencia que
`tests/gui_smoke/test_app_smoke.py` aplicó a la versión Tkinter.

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

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402


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


def test_discovery_run_populates_session_state_and_dock(qapp, main_window, tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)

    _run_discovery_and_wait(qapp, main_window, "Campo de prueba", [(str(path), "OIII")])

    assert main_window._discovery_job is None
    assert not main_window.discovery_progress.isVisible()
    assert len(main_window.session_state.candidates) >= 2
    assert main_window.candidates_dock_widget.title_label.text().startswith(str(len(main_window.session_state.candidates)))


def test_discovery_cancel_stops_before_completion(qapp, main_window, tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30)])
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)

    main_window._start_discovery("Campo cancelado", [(str(path), "HA")])
    main_window._cancel_discovery()

    deadline = time.monotonic() + 10.0
    while main_window._discovery_job is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)

    assert main_window._discovery_job is None
    assert not main_window.cancel_discovery_action.isEnabled()


def test_opening_candidate_detail_creates_single_reusable_mdi_window(qapp, main_window, tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo detalle", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    candidate_id = main_window.session_state.candidates[0].candidate_id
    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    windows_after_first_open = len(main_window.mdi.subWindowList())

    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    assert len(main_window.mdi.subWindowList()) == windows_after_first_open  # reutiliza, no duplica


def test_review_flow_updates_session_state_and_disables_buttons(qapp, main_window, tmp_path):
    from astrophysics_suite.core.enums import ReviewState
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from qt_app.candidates import candidate_detail_widget as cdw

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo revisión", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    candidate_id = main_window.session_state.candidates[0].candidate_id
    main_window._open_candidate_detail(candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate_id].widget()

    with mock.patch.object(cdw.QInputDialog, "getMultiLineText", return_value=("Confirmado en prueba de humo", True)):
        detail_widget._review(ReviewState.KEPT)
    qapp.processEvents()

    updated = [c for c in main_window.session_state.candidates if c.candidate_id == candidate_id][0]
    assert updated.review_state == ReviewState.KEPT
    assert len(updated.review_notes) == 1
    assert not detail_widget.keep_button.isEnabled()
    assert not detail_widget.reject_button.isEnabled()


def test_candidate_detail_shows_real_flux_measured_by_aperture_photometry(qapp, main_window, tmp_path):
    # Cierre del motor de fotometría de apertura (Fase 5, GUI): la fila
    # "Flujo (banda)" de la sección de resumen existía desde antes pero
    # nunca mostraba nada porque `candidate.flux` llegaba vacío -- esto
    # confirma que ahora sí renderiza un número real, no que el widget
    # simplemente existe.
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo flujo", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    candidate = main_window.session_state.candidates[0]
    assert "OIII" in candidate.flux, "el propio candidato debe traer ya el flujo medido"

    main_window._open_candidate_detail(candidate.candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate.candidate_id].widget()

    labels = detail_widget.findChildren(QLabel)
    texts = [label.text() for label in labels]
    assert "Flujo (OIII)" in texts, texts
    flux_value_label = labels[texts.index("Flujo (OIII)") + 1]
    assert "NO DISPONIBLE" not in flux_value_label.text()
    assert "adu" in flux_value_label.text()


def test_new_observation_dialog_rejects_empty_target_name(qapp, main_window):
    from qt_app.candidates.new_observation_dialog import NewObservationDialog

    dialog = NewObservationDialog(main_window)
    dialog._add_row("/tmp/does-not-need-to-exist.fits")
    with mock.patch("qt_app.candidates.new_observation_dialog.QMessageBox.warning") as warning:
        dialog._on_accept()
    warning.assert_called_once()


def test_new_observation_dialog_bulk_band_applies_to_all_rows(qapp, main_window):
    from qt_app.candidates.new_observation_dialog import NewObservationDialog

    dialog = NewObservationDialog(main_window)
    dialog._add_row("/tmp/a.fits")
    dialog._add_row("/tmp/b.fits")
    dialog._add_row("/tmp/c.fits")
    assert [combo.currentText() for _, combo in dialog._rows] == ["OIII", "OIII", "OIII"]

    dialog.bulk_band_combo.setCurrentText("HA")
    dialog._apply_band_to_all()

    assert [combo.currentText() for _, combo in dialog._rows] == ["HA", "HA", "HA"]
    assert dialog.result_images() == [("/tmp/a.fits", "HA"), ("/tmp/b.fits", "HA"), ("/tmp/c.fits", "HA")]


def test_new_observation_dialog_new_rows_inherit_bulk_band(qapp, main_window, tmp_path, monkeypatch):
    from qt_app.candidates.new_observation_dialog import NewObservationDialog

    dialog = NewObservationDialog(main_window)
    dialog.bulk_band_combo.setCurrentText("SII")

    paths = [str(tmp_path / "x.fits"), str(tmp_path / "y.fits")]
    monkeypatch.setattr(
        "qt_app.candidates.new_observation_dialog.QFileDialog.getOpenFileNames", lambda *a, **k: (paths, "")
    )
    dialog._add_images()

    assert [combo.currentText() for _, combo in dialog._rows] == ["SII", "SII"]
