"""Prueba de humo de extremo a extremo del respaldo de GAIN/RDNOISE por
perfil de instrumento guardado (§63-78, "base de datos de perfiles de
instrumento"): un perfil real guardado con `InstrumentProfileStore`
(Fase 10.2, ya usado por "Reducir sesión de LIGHTS") ahora también se
ofrece como respaldo de ruido real en `spectroscopy.trace` cuando la
cabecera FITS de la exposición concreta no trae `GAIN`/`RDNOISE`.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import logging
import time

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtCore import Qt, QPointF  # noqa: E402
from PySide6.QtGui import QMouseEvent  # noqa: E402
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


def _click(view, scene_x: float, scene_y: float, button: Qt.MouseButton) -> None:
    view_point = view.mapFromScene(QPointF(scene_x, scene_y))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(view_point), button, button, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(event)


def test_saved_instrument_profile_backs_the_real_noise_model_in_spectral_trace(qapp, tmp_path, caplog):
    caplog.set_level(logging.INFO)
    from services.instrument_profiles import InstrumentProfile, InstrumentProfileStore

    store = InstrumentProfileStore(tmp_path / "profiles.json")
    store.save(InstrumentProfile(name="ZWO ASI294MM", gain_e_per_adu=1.2, read_noise_e=3.0))

    from qt_app.main_window import MainWindow

    window = MainWindow(instrument_profile_store=store)
    window.show()
    qapp.processEvents()
    try:
        process = window._process_by_id["spectroscopy.trace"]
        profile_param = next(p for p in process.parameters if p.name == "instrument_profile")
        assert "ZWO ASI294MM" in profile_param.choices

        height, width = 41, 150
        yy, _xx = np.mgrid[0:height, 0:width]
        profile_shape = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
        profile_shape /= profile_shape.sum(axis=0, keepdims=True)
        data = 80.0 + 3000.0 * profile_shape  # sin GAIN/RDNOISE reales en la cabecera FITS

        sub_window = window.add_image_window(data, "no_gain_header.fits")
        window.mdi.setActiveSubWindow(sub_window)
        qapp.processEvents()
        view = sub_window.widget()

        params = {p.name: p.default for p in process.parameters}
        params["instrument_profile"] = "ZWO ASI294MM"
        window._run_process("spectroscopy.trace", params)
        qapp.processEvents()
        assert view._picking is True

        _click(view, 0.0, 20.0, Qt.MouseButton.LeftButton)
        qapp.processEvents()

        deadline = time.monotonic() + 10.0
        while window._active_worker is not None and time.monotonic() < deadline:
            qapp.processEvents()
            time.sleep(0.02)
        qapp.processEvents()

        assert any("ZWO ASI294MM" in record.message for record in caplog.records)
    finally:
        window.close()
