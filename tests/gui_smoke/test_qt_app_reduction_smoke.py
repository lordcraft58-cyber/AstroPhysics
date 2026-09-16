"""Prueba de humo de la vista de conjunto de fotogramas (Fase 9.6,
continuación): construir un fotograma maestro real a partir de varios
FITS sintéticos escritos a disco, y aplicar la calibración resultante a
la imagen activa -- de principio a fin, con el hilo de fondo real
(`CallableWorker`) incluido.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import time

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


@pytest.fixture
def main_window(qapp):
    from qt_app.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


FRAME_SHAPE = (30, 30)


def _write_bias_frames(tmp_path, n=4, level=500.0, seed=0):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    rng = np.random.default_rng(seed)
    paths = []
    for i in range(n):
        frame = np.full(FRAME_SHAPE, level, dtype=np.float32) + rng.normal(0, 2.0, FRAME_SHAPE).astype(np.float32)
        path = tmp_path / f"bias_{i}.fits"
        _write_minimal_fits_2d(path, frame)
        paths.append(str(path))
    return paths


def _wait_worker(qapp, dialog_attr_owner, attr="_worker", timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while getattr(dialog_attr_owner, attr) is not None and getattr(dialog_attr_owner, attr).isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def test_build_master_bias_end_to_end(qapp, main_window, tmp_path):
    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog

    from services.app_preferences import AppPreferencesStore

    paths = _write_bias_frames(tmp_path, n=4, level=500.0)
    preferences = AppPreferencesStore(tmp_path / "prefs.json")
    dialog = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=preferences)
    dialog.kind_combo.setCurrentText("Bias")
    dialog.name_edit.setText("Bias-test")

    # el diálogo real añade archivos vía QFileDialog (no automatizable aquí);
    # se inyectan directamente en la lista con el rol de datos que `_selected_paths` espera.
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        dialog.file_list.addItem(item)

    output_path = tmp_path / "masters" / "Bias-test.fits"
    dialog.output_path_edit.setText(str(output_path))
    dialog._on_combine()
    _wait_worker(qapp, dialog)

    assert "Bias-test" in main_window.master_frame_library.all_names()
    master = main_window.master_frame_library.get("Bias-test")
    assert master.kind == "bias"
    assert master.data.shape == FRAME_SHAPE
    assert abs(float(np.median(master.data)) - 500.0) < 5.0

    entry = main_window.master_frame_library.entry("Bias-test")
    assert entry.path == str(output_path)
    assert output_path.exists()
    assert entry.saved_at is not None
    assert preferences.get("last_master_frame_dir") == str(output_path.parent)


def test_apply_calibration_end_to_end_creates_calibrated_window(qapp, main_window, tmp_path):
    from qt_app.reduction.apply_calibration_dialog import ApplyCalibrationDialog

    from services.app_preferences import AppPreferencesStore

    paths = _write_bias_frames(tmp_path, n=4, level=300.0, seed=1)
    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog

    builder = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    builder.kind_combo.setCurrentText("Bias")
    builder.name_edit.setText("Bias-cal")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        builder.file_list.addItem(item)
    builder.output_path_edit.setText(str(tmp_path / "masters" / "Bias-cal.fits"))
    builder._on_combine()
    _wait_worker(qapp, builder)
    assert "Bias-cal" in main_window.master_frame_library.all_names()

    raw = np.full((30, 30), 1300.0)
    sub_window = main_window.add_image_window(raw, "raw_science.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    windows_before = len(main_window.mdi.subWindowList())
    dialog = ApplyCalibrationDialog(main_window.master_frame_library, raw, main_window)
    dialog.bias_combo.setCurrentText("Bias-cal")
    received = {}
    dialog.calibrated.connect(lambda data, summary: received.update(data=data, summary=summary))
    dialog._on_apply()
    _wait_worker(qapp, dialog)

    assert "data" in received
    np.testing.assert_allclose(received["data"], 1300.0 - 300.0, atol=5.0)
    assert "bias restado" in received["summary"]

    main_window._on_calibration_applied(sub_window.widget(), received["data"], received["summary"])
    qapp.processEvents()
    assert len(main_window.mdi.subWindowList()) == windows_before + 1


def test_build_master_dark_records_exposure_and_saves_real_fits(qapp, main_window, tmp_path):
    """Prueba obligatoria I: dark con exposición registrada, guardado en
    la ruta elegida, y la exposición sobrevive reabrir el archivo."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from astrophysics_suite.reduction.master_frames import load_master_frame
    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
    from services.app_preferences import AppPreferencesStore

    rng = np.random.default_rng(2)
    paths = []
    for i in range(4):
        frame = np.full(FRAME_SHAPE, 520.0, dtype=np.float32) + rng.normal(0, 2.0, FRAME_SHAPE).astype(np.float32)
        path = tmp_path / f"dark_{i}.fits"
        from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

        _write_minimal_fits_2d(path, frame)
        paths.append(str(path))

    dialog = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    dialog.kind_combo.setCurrentText("Dark")
    dialog.name_edit.setText("Dark-120s")
    dialog.exposure_spin.setValue(120.0)
    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        dialog.file_list.addItem(item)
    output_path = tmp_path / "Dark-120s.fits"
    dialog.output_path_edit.setText(str(output_path))
    dialog._on_combine()
    _wait_worker(qapp, dialog)

    assert "Dark-120s" in main_window.master_frame_library.all_names()
    master = main_window.master_frame_library.get("Dark-120s")
    assert master.exposure_s == pytest.approx(120.0)

    reloaded = load_master_frame(str(output_path))
    assert reloaded.kind == "dark"
    assert reloaded.exposure_s == pytest.approx(120.0)


def test_build_master_flat_normalizes_and_saves_real_fits(qapp, main_window, tmp_path):
    """Prueba obligatoria J: flat normalizado a mediana 1.0, guardado en
    la ruta elegida y reutilizable tras reabrir el archivo."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    from astrophysics_suite.reduction.master_frames import load_master_frame
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
    from services.app_preferences import AppPreferencesStore

    rng = np.random.default_rng(6)
    paths = []
    for i in range(5):
        frame = np.full(FRAME_SHAPE, 30000.0, dtype=np.float32) + rng.normal(0, 50.0, FRAME_SHAPE).astype(np.float32)
        frame[0:5, 0:5] *= 0.8  # viñeteado real en una esquina
        path = tmp_path / f"flat_{i}.fits"
        _write_minimal_fits_2d(path, frame)
        paths.append(str(path))

    dialog = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    dialog.kind_combo.setCurrentText("Flat")
    dialog.name_edit.setText("Flat-HA")
    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        dialog.file_list.addItem(item)
    output_path = tmp_path / "Flat-HA.fits"
    dialog.output_path_edit.setText(str(output_path))
    dialog._on_combine()
    _wait_worker(qapp, dialog)

    assert "Flat-HA" in main_window.master_frame_library.all_names()
    master = main_window.master_frame_library.get("Flat-HA")
    assert master.kind == "flat"
    assert np.median(master.data) == pytest.approx(1.0, abs=1e-3)
    assert master.data[0, 0] == pytest.approx(0.8, abs=0.05)

    reloaded = load_master_frame(str(output_path))
    assert reloaded.kind == "flat"
    np.testing.assert_allclose(reloaded.data, master.data, atol=1e-4)


def test_build_master_frame_requires_confirmation_before_overwriting(qapp, main_window, tmp_path, monkeypatch):
    """Prueba obligatoria K: si ya existe un archivo en la ruta elegida,
    se pide confirmación -- "No" no debe tocar el archivo existente."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem, QMessageBox
    from astropy.io import fits

    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
    from services.app_preferences import AppPreferencesStore

    paths = _write_bias_frames(tmp_path, n=4, level=400.0, seed=3)
    output_path = tmp_path / "Bias-overwrite.fits"
    sentinel = np.full((3, 3), -999.0, dtype=np.float32)
    fits.PrimaryHDU(sentinel).writeto(output_path)

    dialog = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    dialog.kind_combo.setCurrentText("Bias")
    dialog.name_edit.setText("Bias-overwrite")
    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        dialog.file_list.addItem(item)
    dialog.output_path_edit.setText(str(output_path))

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.No))
    dialog._on_combine()
    qapp.processEvents()
    assert dialog._worker is None or not dialog._worker.isRunning()
    assert "Bias-overwrite" not in main_window.master_frame_library.all_names()
    with fits.open(output_path) as hdul:
        np.testing.assert_array_equal(hdul[0].data, sentinel)  # nunca tocado

    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    dialog._on_combine()
    _wait_worker(qapp, dialog)
    assert "Bias-overwrite" in main_window.master_frame_library.all_names()
    with fits.open(output_path) as hdul:
        assert hdul[0].data.shape == FRAME_SHAPE  # sí sobrescrito tras confirmar


def test_load_master_frame_dialog_reuses_a_previously_saved_master(qapp, main_window, tmp_path, monkeypatch):
    """Prueba obligatoria (reutilización en sesiones posteriores): un
    fotograma maestro guardado a disco se puede recargar en una
    biblioteca "nueva" (aquí, un MainWindow recién creado) vía "Cargar
    fotograma maestro..." y queda disponible para calibrar de verdad --
    no solo "aparece en la lista"."""
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QFileDialog, QInputDialog, QListWidgetItem

    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
    from services.app_preferences import AppPreferencesStore

    paths = _write_bias_frames(tmp_path, n=4, level=600.0, seed=5)
    output_path = tmp_path / "Bias-persisted.fits"
    builder = BuildMasterFrameDialog(main_window.master_frame_library, main_window, preferences=AppPreferencesStore(tmp_path / "prefs.json"))
    builder.kind_combo.setCurrentText("Bias")
    builder.name_edit.setText("Bias-persisted")
    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        builder.file_list.addItem(item)
    builder.output_path_edit.setText(str(output_path))
    builder._on_combine()
    _wait_worker(qapp, builder)
    assert output_path.exists()

    from qt_app.main_window import MainWindow

    fresh_window = MainWindow()
    try:
        assert "Bias-persisted" not in fresh_window.master_frame_library.all_names()
        monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(output_path), "")))
        monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Bias-recargado", True)))
        fresh_window._open_load_master_frame_dialog()

        assert "Bias-recargado" in fresh_window.master_frame_library.all_names()
        entry = fresh_window.master_frame_library.entry("Bias-recargado")
        assert entry.path == str(output_path)
        reloaded_master = fresh_window.master_frame_library.get("Bias-recargado")
        assert reloaded_master.kind == "bias"
        assert abs(float(np.median(reloaded_master.data)) - 600.0) < 5.0

        # y de verdad se puede usar en una calibración, no solo listarse.
        from qt_app.reduction.apply_calibration_dialog import ApplyCalibrationDialog

        raw = np.full(FRAME_SHAPE, 1600.0)
        cal_dialog = ApplyCalibrationDialog(fresh_window.master_frame_library, raw, fresh_window)
        cal_dialog.bias_combo.setCurrentText("Bias-recargado")
        received = {}
        cal_dialog.calibrated.connect(lambda data, summary: received.update(data=data, summary=summary))
        cal_dialog._on_apply()
        _wait_worker(qapp, cal_dialog)
        assert "data" in received
        np.testing.assert_allclose(received["data"], 1600.0 - 600.0, atol=5.0)
    finally:
        fresh_window.close()


def test_master_frame_library_names_for_kind(qapp):
    from astrophysics_suite.reduction.master_frames import MasterFrame
    from qt_app.reduction.master_frame_library import MasterFrameLibrary

    library = MasterFrameLibrary()
    library.add("B1", MasterFrame(data=np.zeros((2, 2)), uncertainty=np.zeros((2, 2)), n_combined=np.full((2, 2), 3), kind="bias"))
    library.add("D1", MasterFrame(data=np.zeros((2, 2)), uncertainty=np.zeros((2, 2)), n_combined=np.full((2, 2), 3), kind="dark", exposure_s=30.0))

    assert library.names_for_kind("bias") == ["B1"]
    assert library.names_for_kind("dark") == ["D1"]
    assert library.names_for_kind("flat") == []
    assert len(library) == 2
