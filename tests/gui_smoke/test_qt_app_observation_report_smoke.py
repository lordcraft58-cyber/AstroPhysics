"""Prueba de humo de "Descubrimiento -> Generar informe de
observación...": ejecuta un análisis real y confirma que el menú
produce un HTML real en disco con los candidatos reales de esa
observación -- mismo nivel de exigencia que
`test_qt_app_report_smoke.py` para el informe por candidato.

Requiere PySide6 y un display X (real o Xvfb) -- si no están disponibles,
el test se salta en vez de fallar por una razón ajena al código bajo
prueba.
"""
from __future__ import annotations

import time

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


def test_observation_report_action_writes_a_real_html_report(qapp, main_window, tmp_path, monkeypatch):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    field = _star_field((96, 96), [(30, 30), (60, 60)])
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field)
    _run_discovery_and_wait(qapp, main_window, "Campo informe observación", [(str(path), "OIII")])
    assert main_window.session_state.candidates
    assert len(main_window.session_state.observations) == 1

    report_path = tmp_path / "informe_observacion.html"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(report_path), "")))

    main_window._generate_observation_report_dialog()
    qapp.processEvents()

    assert report_path.exists()
    text = report_path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert "Campo informe observación" in text
    assert str(len(main_window.session_state.candidates)) in text
    assert report_path.name in main_window.statusBar().currentMessage()


def test_observation_report_action_warns_instead_of_opening_a_dialog_with_no_observations(qapp, main_window, monkeypatch):
    def _fail_if_called(*a, **k):
        raise AssertionError("no debería abrirse el diálogo de guardado sin ninguna observación")

    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(_fail_if_called))
    main_window._generate_observation_report_dialog()
    assert "primero" in main_window.statusBar().currentMessage() or "No hay" in main_window.statusBar().currentMessage()
