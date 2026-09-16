"""Prueba de humo de extremo a extremo del flujo que cierra el hueco
principal de `ccdred` señalado por el Mapa de capacidades IRAF
(`docs/audit/13-IRAF-CAPABILITY-MAP.md`): reducir una SESIÓN real de
varias LIGHTS (no una imagen a la vez), con bias/dark/flat maestros,
corrección de píxeles defectuosos y combinación final con rechazo de
outliers -- FITS reales escritos a disco, hilo de fondo real
(`CallableWorker`), productos calibrados reales releídos de disco al
final para confirmar los valores.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from astropy.io import fits

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QListWidgetItem  # noqa: E402


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


def _wait_worker(qapp, dialog, attr="_worker", timeout_s=10.0):
    deadline = time.monotonic() + timeout_s
    while getattr(dialog, attr) is not None and getattr(dialog, attr).isRunning() and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()


def _inject_paths(list_widget, paths):
    for path in paths:
        item = QListWidgetItem(Path(path).name)
        item.setData(Qt.ItemDataRole.UserRole, path)
        list_widget.addItem(item)


SHAPE = (20, 24)
DEFECT_PIXEL = (5, 5)
SPIKE_PIXEL = (10, 10)


def _write_calibration_frames(tmp_path):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d

    bias_paths, dark_paths, flat_paths = [], [], []
    for i in range(4):
        bias = np.full(SHAPE, 500.0, dtype=np.float32)
        path = tmp_path / f"bias_{i}.fits"
        _write_minimal_fits_2d(path, bias)
        bias_paths.append(str(path))

        dark = np.full(SHAPE, 540.0, dtype=np.float32)  # 500 bias + 40 corriente de oscuridad a 60s
        path = tmp_path / f"dark_{i}.fits"
        _write_minimal_fits_2d(path, dark)
        dark_paths.append(str(path))

        flat = np.full(SHAPE, 1300.0, dtype=np.float32)  # 500 bias + 800 señal de plano
        flat[DEFECT_PIXEL] = 550.0  # 500 bias + 50: píxel defectuoso real, presente en todos los planos
        path = tmp_path / f"flat_{i}.fits"
        _write_minimal_fits_2d(path, flat)
        flat_paths.append(str(path))

    return bias_paths, dark_paths, flat_paths


def _write_light_frames(tmp_path, n=3, exptime_s=60.0):
    paths = []
    for i in range(n):
        raw = np.full(SHAPE, 1540.0, dtype=np.float32)  # 500 bias + 40 dark + 1000 ciencia (flat normalizado=1.0)
        raw[DEFECT_PIXEL] = 602.5  # 500 + 40 + 1000*0.0625 (respuesta relativa real del píxel defectuoso)
        if i == 1:
            raw[SPIKE_PIXEL] += 80000.0  # rayo cósmico -- solo en esta LIGHT
        path = tmp_path / f"light_{i}.fits"
        hdu = fits.PrimaryHDU(raw)
        hdu.header["EXPTIME"] = exptime_s
        hdu.writeto(path)
        paths.append(str(path))
    return paths


def test_reduce_session_dialog_end_to_end_writes_calibrated_products(qapp, main_window, tmp_path):
    from astrophysics_suite.reduction.master_frames import build_master_bias, build_master_dark, build_master_flat
    from astrophysics_suite.io.fits_loader import load_image
    from qt_app.reduction.reduce_session_dialog import ReduceSessionDialog

    bias_paths, dark_paths, flat_paths = _write_calibration_frames(tmp_path)
    bias_frames = [load_image(p, band="", role="calibration").legacy_image.data for p in bias_paths]
    dark_frames = [load_image(p, band="", role="calibration").legacy_image.data for p in dark_paths]
    flat_frames = [load_image(p, band="", role="calibration").legacy_image.data for p in flat_paths]

    bias_master = build_master_bias(bias_frames)
    dark_master = build_master_dark(dark_frames, exposure_s=60.0, master_bias=bias_master.data)
    flat_master = build_master_flat(flat_frames, master_bias=bias_master.data)
    main_window.master_frame_library.add("Bias-session", bias_master)
    main_window.master_frame_library.add("Dark-session", dark_master)
    main_window.master_frame_library.add("Flat-session", flat_master)

    light_paths = _write_light_frames(tmp_path, n=3, exptime_s=60.0)
    output_dir = tmp_path / "reduced"

    dialog = ReduceSessionDialog(main_window.master_frame_library, main_window)
    dialog.session_reduced.connect(main_window._on_session_reduced)
    _inject_paths(dialog.file_list, light_paths)
    dialog.bias_combo.setCurrentText("Bias-session")
    dialog.dark_combo.setCurrentText("Dark-session")
    dialog.flat_combo.setCurrentText("Flat-session")
    assert dialog.bad_pixel_check.isEnabled()
    dialog.bad_pixel_check.setChecked(True)
    dialog._output_dir = str(output_dir)
    assert dialog.combine_group.isChecked()  # combinación activada por defecto

    windows_before = len(main_window.mdi.subWindowList())
    dialog._on_run()
    _wait_worker(qapp, dialog)

    assert dialog.status_label.text() == ""  # sin error

    for i in range(3):
        out_path = output_dir / f"light_{i}_calibrada.fits"
        assert out_path.exists()
        with fits.open(out_path) as hdul:
            data = hdul[0].data.copy()
        if i == 1:
            # el rayo cósmico es real en esta LIGHT individual -- solo la
            # combinación final lo rechaza, cada fotograma calibrado por
            # separado debe conservar sus propios píxeles tal cual.
            np.testing.assert_allclose(data[SPIKE_PIXEL], 81000.0, atol=1e-3)
            data[SPIKE_PIXEL] = 1000.0
        np.testing.assert_allclose(data, 1000.0, atol=1e-3)  # incluye el píxel defectuoso, ya interpolado

    combined_path = output_dir / "combinada.fits"
    assert combined_path.exists()
    with fits.open(combined_path) as hdul:
        combined_data = hdul[0].data
    np.testing.assert_allclose(combined_data, 1000.0, atol=1e-3)  # el rayo cósmico de la LIGHT 1 fue rechazado

    assert len(main_window.mdi.subWindowList()) == windows_before + 1  # el combinado se abrió como ventana MDI


def test_reduce_session_dialog_reports_missing_exptime_without_crashing(qapp, main_window, tmp_path, monkeypatch):
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d
    from astrophysics_suite.reduction.master_frames import build_master_dark
    import qt_app.reduction.reduce_session_dialog as reduce_session_dialog_module

    shown = {}
    monkeypatch.setattr(
        reduce_session_dialog_module.QMessageBox, "critical", lambda *args, **kwargs: shown.update(called=True)
    )
    from qt_app.reduction.reduce_session_dialog import ReduceSessionDialog

    dark_frames = [np.full(SHAPE, 40.0, dtype=np.float32) for _ in range(4)]
    dark_master = build_master_dark(dark_frames, exposure_s=60.0)
    main_window.master_frame_library.add("Dark-noexp", dark_master)

    light_path = tmp_path / "light_no_exptime.fits"
    _write_minimal_fits_2d(light_path, np.full(SHAPE, 1000.0, dtype=np.float32))  # sin EXPTIME en la cabecera

    dialog = ReduceSessionDialog(main_window.master_frame_library, main_window)
    _inject_paths(dialog.file_list, [str(light_path)])
    dialog.dark_combo.setCurrentText("Dark-noexp")
    dialog._output_dir = str(tmp_path / "out")
    dialog.combine_group.setChecked(False)

    dialog._on_run()
    _wait_worker(qapp, dialog)

    assert "EXPTIME" in dialog.status_label.text()
    assert shown.get("called") is True
    assert not (tmp_path / "out").exists() or not list((tmp_path / "out").glob("*.fits"))
