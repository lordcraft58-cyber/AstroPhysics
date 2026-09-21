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

import math
import time
from unittest import mock

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QFileDialog, QLabel  # noqa: E402


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


def test_saving_and_reopening_a_session_roundtrips_real_candidates_via_the_menu(qapp, main_window, tmp_path, monkeypatch):
    # Cierre del motor de persistencia de sesión: "Guardar sesión..."/
    # "Abrir sesión..." (Archivo) sobre un análisis real de Descubrimiento,
    # no una llamada directa a `save_session`/`load_session` -- confirma
    # que el cableado completo de la GUI (diálogo nativo, `SessionState`,
    # refresco del panel) funciona de extremo a extremo.
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo persistencia", [(str(path), "OIII")])
    original_candidates = list(main_window.session_state.candidates)
    assert original_candidates

    session_path = tmp_path / "session.apssession.json"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(session_path), "")))
    main_window._save_session_dialog()
    assert session_path.exists()

    from astrophysics_suite.io.session_export import load_session

    on_disk = load_session(str(session_path))
    assert list(on_disk.candidates) == original_candidates

    # "Abrir sesión..." SUMA a la sesión en memoria (nunca descarta
    # análisis en curso) -- tras reabrir el mismo archivo, cada
    # candidato original debe aparecer duplicado una vez más.
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(session_path), "")))
    main_window._open_session_dialog()
    qapp.processEvents()

    assert len(main_window.session_state.candidates) == 2 * len(original_candidates)
    for candidate in original_candidates:
        assert main_window.session_state.candidates.count(candidate) == 2


def test_recent_sessions_menu_lists_and_reopens_a_real_saved_session(qapp, tmp_path, monkeypatch):
    # Antes no había ninguna forma de reabrir una sesión reciente salvo
    # recordar la ruta a mano -- ahora "Archivo -> Sesiones recientes"
    # lista de verdad lo que se guardó/abrió en esta máquina y permite
    # reabrirlo con un clic, sin volver a pasar por el diálogo nativo.
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from qt_app.main_window import MainWindow
    from services.app_preferences import AppPreferencesStore

    window = MainWindow(preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    try:
        assert len(window.recent_sessions_menu.actions()) == 1
        assert not window.recent_sessions_menu.actions()[0].isEnabled()

        field = _star_field((96, 96), [(30, 30), (60, 60)])
        path = tmp_path / "field_OIII.fits"
        _write_minimal_fits_2d(path, field)
        window._start_discovery("Campo sesiones recientes", [(str(path), "OIII")])
        deadline = time.monotonic() + 10.0
        while window._discovery_job is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        qapp.processEvents()
        assert window.session_state.candidates
        original_candidates = list(window.session_state.candidates)

        session_path = tmp_path / "sesion.apssession.json"
        monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(session_path), "")))
        window._save_session_dialog()

        actions = window.recent_sessions_menu.actions()
        assert len(actions) == 1
        assert actions[0].isEnabled()
        assert actions[0].text() == session_path.name
        assert actions[0].toolTip() == str(session_path)

        # Reabrir desde el menú -- sin volver a pasar por QFileDialog.
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (_ for _ in ()).throw(AssertionError("no debería abrirse el diálogo nativo"))))
        actions[0].trigger()
        qapp.processEvents()

        assert len(window.session_state.candidates) == 2 * len(original_candidates)
    finally:
        window.close()


def test_save_session_dialog_warns_instead_of_opening_a_dialog_when_there_is_nothing_to_save(qapp, main_window, monkeypatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("no debería abrirse el diálogo de guardado sin nada que guardar")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_fail_if_called))
    main_window._save_session_dialog()
    assert "nada que guardar" in main_window.statusBar().currentMessage() or "primero" in main_window.statusBar().currentMessage()


def test_open_session_dialog_reports_a_real_error_for_a_corrupt_file(qapp, main_window, tmp_path, monkeypatch):
    from unittest import mock

    bad_path = tmp_path / "corrupt.apssession.json"
    bad_path.write_text("{ esto no es JSON valido", encoding="utf-8")
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(bad_path), "")))

    with mock.patch("qt_app.main_window.QMessageBox.critical") as critical:
        main_window._open_session_dialog()

    critical.assert_called_once()
    assert main_window.session_state.candidates == []


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

    with (
        mock.patch.object(cdw.QInputDialog, "getText", return_value=("Revisor de prueba", True)),
        mock.patch.object(cdw.QInputDialog, "getMultiLineText", return_value=("Confirmado en prueba de humo", True)),
    ):
        detail_widget._review(ReviewState.KEPT)
    qapp.processEvents()

    updated = [c for c in main_window.session_state.candidates if c.candidate_id == candidate_id][0]
    assert updated.review_state == ReviewState.KEPT
    assert len(updated.review_notes) == 1
    assert updated.review_notes[0].author == "Revisor de prueba"
    assert not detail_widget.keep_button.isEnabled()
    assert not detail_widget.reject_button.isEnabled()


def test_reviewer_name_is_persisted_and_prefilled_on_the_next_review(qapp, main_window, tmp_path):
    # Antes REVIEWER_NAME era un placeholder fijo ("Revisor") -- ahora es
    # el nombre real que el revisor teclea la primera vez, persistido
    # como preferencia y reutilizado como valor por defecto la próxima
    # vez, sin inventar un sistema de usuarios completo.
    from astrophysics_suite.core.enums import ReviewState
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from qt_app.candidates import candidate_detail_widget as cdw
    from qt_app.theme import DARK
    from services.app_preferences import AppPreferencesStore

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo nombre revisor", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    isolated_preferences = AppPreferencesStore(tmp_path / "prefs.json")
    widget = cdw.CandidateDetailWidget(
        main_window.session_state.candidates[0].candidate_id, main_window.session_state, DARK,
        preferences=isolated_preferences,
    )

    prefill_holder: list[str] = []

    def _capture_prefill(parent, title, label, text=""):
        prefill_holder.append(text)
        return "María Revisora", True

    with (
        mock.patch.object(cdw.QInputDialog, "getText", side_effect=_capture_prefill),
        mock.patch.object(cdw.QInputDialog, "getMultiLineText", return_value=("primera revisión", True)),
    ):
        widget._review(ReviewState.KEPT)
    qapp.processEvents()

    assert prefill_holder[0] == cdw.DEFAULT_REVIEWER_NAME
    assert isolated_preferences.get(cdw._REVIEWER_NAME_PREFERENCE_KEY) == "María Revisora"


def _field_with_calibratable_flux_and_catalog(shape=(180, 180), *, true_zeropoint_mag=24.0, n_stars=6, anomalous_index=0, anomalous_factor=6.0, seed=13):
    """Mismo generador que
    `tests/integration/test_generic_discovery_pipeline.py::_field_with_calibratable_flux_and_catalog`
    (independiente aquí, como el resto de las pruebas de humo GUI de
    este archivo, que no importan helpers de otros archivos de test):
    flujo verdadero distinto por estrella + magnitud de catálogo
    derivada de ese flujo vía un punto cero real, con una estrella cuyo
    flujo inyectado se hace deliberadamente inconsistente con su propia
    magnitud de catálogo."""
    from astropy.wcs import WCS

    height, width = shape
    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [width / 2.0, height / 2.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [210.0, -8.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    rng = np.random.default_rng(seed)
    margin = 25.0
    xs = rng.uniform(margin, width - margin, n_stars)
    ys = rng.uniform(margin, height - margin, n_stars)
    ra, dec = wcs.all_pix2world(xs, ys, 0)

    true_fluxes = rng.uniform(15000.0, 60000.0, n_stars)
    catalog_mags = true_zeropoint_mag - 2.5 * np.log10(true_fluxes)
    injected_fluxes = true_fluxes.copy()
    if anomalous_index is not None:
        injected_fluxes[anomalous_index] *= anomalous_factor

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    sigma = 1.6
    for x0, y0, flux in zip(xs, ys, injected_fluxes):
        data += flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data += rng.normal(0, 3.0, shape)

    gaia_rows = [
        {"ra_deg": float(r), "dec_deg": float(d), "source_id": f"GAIA-{i}", "mag_g": float(m)}
        for i, (r, d, m) in enumerate(zip(ra, dec, catalog_mags))
    ]
    return data.astype(np.float32), wcs.to_header(), gaia_rows


def test_candidate_detail_shows_real_photometric_anomaly_from_field_zeropoint_fit(qapp, main_window, tmp_path, monkeypatch):
    # Cierre del motor de calibración fotométrica (Fase 5, GUI): la fila
    # "Photometric" del vector de anomalía ya existía en el detalle de
    # candidato pero estaba siempre en "NO DISPONIBLE" porque
    # `discovery/pipeline.py` nunca ajustaba un punto cero real ni pasaba
    # `expected_band_flux` a `build_anomaly_vector` -- esto confirma que
    # ahora, con estrellas KNOWN reales de sobra en la imagen, renderiza
    # una significancia real (en sigma), no que el widget simplemente
    # exista.
    from astropy.io import fits

    import astrophysics_suite.catalogs.gaia as gaia_module
    from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg

    data, header, gaia_rows = _field_with_calibratable_flux_and_catalog()

    def _gaia_mock(ra, dec, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra, dec, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    monkeypatch.setattr(gaia_module, "query_gaia_neighbors", _gaia_mock)

    path = tmp_path / "field_zeropoint.fits"
    fits.PrimaryHDU(data, header=header).writeto(path)
    _run_discovery_and_wait(qapp, main_window, "Campo punto cero", [(str(path), "OIII")])

    from astrophysics_suite.core.enums import IdentificationState

    known = [c for c in main_window.session_state.candidates if c.identification_state is IdentificationState.KNOWN]
    assert len(known) >= 5, "la prueba necesita suficientes estrellas KNOWN reales para que el ajuste de punto cero se dispare"
    with_photometric = [c for c in known if c.anomaly_evidence is not None and c.anomaly_evidence.photometric.is_available]
    assert with_photometric, "con estrellas KNOWN suficientes, al menos un candidato debe tener dimensión fotométrica real"

    main_window._open_candidate_detail(with_photometric[0].candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[with_photometric[0].candidate_id].widget()

    labels = detail_widget.findChildren(QLabel)
    texts = [label.text() for label in labels]
    assert "Photometric" in texts, texts
    photometric_value_label = labels[texts.index("Photometric") + 1]
    assert "NO DISPONIBLE" not in photometric_value_label.text()
    assert "sigma" in photometric_value_label.text()


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


def test_candidate_detail_shows_the_real_artifact_checklist_not_just_flagged_ones(qapp, main_window, tmp_path):
    # Cierre del motor de rechazo de artefactos (informe 87): un
    # `Candidate` real solo existe si NINGUNA comprobación de
    # `screen_detection` quedó marcada (la detección se descarta antes de
    # llegar a ser candidato), así que filtrar aquí por `artifact.flagged`
    # nunca mostraba ninguna fila -- código muerto que ocultaba qué se
    # había comprobado de verdad. Confirma que ahora sí aparece el
    # checklist real (categorías evaluadas y limpias, categorías no
    # evaluables con su motivo) para un candidato real de un análisis de
    # Descubrimiento de extremo a extremo, no solo a nivel de unidad.
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_artifact_checklist.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo checklist de artefactos", [(str(path), "OIII")])
    assert main_window.session_state.candidates

    candidate = main_window.session_state.candidates[0]
    assert candidate.artifact_checks, "el candidato real debe traer ya las comprobaciones de artefactos"
    assert not any(check.flagged for check in candidate.artifact_checks), (
        "un Candidate real nunca puede tener una comprobación marcada -- screen_detection lo habría rechazado antes"
    )

    main_window._open_candidate_detail(candidate.candidate_id)
    qapp.processEvents()
    detail_widget = main_window._candidate_detail_windows[candidate.candidate_id].widget()

    texts = [label.text() for label in detail_widget.findChildren(QLabel)]
    assert any("(limpio)" in text for text in texts), texts
    assert any("(no evaluable)" in text for text in texts), texts
    assert not any("(ARTEFACTO)" in text for text in texts), texts


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
