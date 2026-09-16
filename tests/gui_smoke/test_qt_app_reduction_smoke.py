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

    paths = _write_bias_frames(tmp_path, n=4, level=500.0)
    dialog = BuildMasterFrameDialog(main_window.master_frame_library, main_window)
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

    dialog._on_combine()
    _wait_worker(qapp, dialog)

    assert "Bias-test" in main_window.master_frame_library.all_names()
    master = main_window.master_frame_library.get("Bias-test")
    assert master.kind == "bias"
    assert master.data.shape == FRAME_SHAPE
    assert abs(float(np.median(master.data)) - 500.0) < 5.0


def test_apply_calibration_end_to_end_creates_calibrated_window(qapp, main_window, tmp_path):
    from qt_app.reduction.apply_calibration_dialog import ApplyCalibrationDialog

    paths = _write_bias_frames(tmp_path, n=4, level=300.0, seed=1)
    from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog

    builder = BuildMasterFrameDialog(main_window.master_frame_library, main_window)
    builder.kind_combo.setCurrentText("Bias")
    builder.name_edit.setText("Bias-cal")
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QListWidgetItem

    for path in paths:
        item = QListWidgetItem(path.split("/")[-1])
        item.setData(Qt.ItemDataRole.UserRole, path)
        builder.file_list.addItem(item)
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
