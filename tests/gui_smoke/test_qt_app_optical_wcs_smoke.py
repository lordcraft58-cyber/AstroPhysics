"""Prueba de humo GUI de "WCS desde la óptica (cámara + focal)": el
diálogo real se rellena solo desde la cabecera real de los lights de
M 31 del usuario (ZWO ASI533MC Pro a 749 mm), calcula la escala y el
campo reales en vivo, avisa cuando la cámara elegida contradice a la
cabecera, y construye un WCS real cableado en la ventana y en la sesión.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication  # noqa: E402

from astrophysics_suite.astrometry.optical_wcs import is_optical_wcs, pixel_scale_of  # noqa: E402
from qt_app.astrometry.optical_wcs_dialog import CUSTOM_CAMERA_OPTION, OpticalWCSDialog  # noqa: E402

_REAL_M31_HEADER = {
    "NAXIS1": 3008, "NAXIS2": 3008,
    "XPIXSZ": 3.75999999046326, "YPIXSZ": 3.75999999046326,
    "FOCALLEN": 749, "INSTRUME": "ZWO ASI533MC Pro",
    "RA": 11.087505, "DEC": 41.412641, "OBJECT": "M 31", "XBINNING": 1,
}


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


def test_dialog_prefills_itself_from_the_real_m31_header(qapp):
    dialog = OpticalWCSDialog((3008, 3008), _REAL_M31_HEADER)
    assert dialog.camera_combo.currentText() == "ZWO ASI533MC Pro"
    assert dialog.pixel_spin.value() == pytest.approx(3.76, abs=1e-3)
    assert dialog.focal_spin.value() == pytest.approx(749.0)
    assert dialog.ra_spin.value() == pytest.approx(11.087505, abs=1e-5)
    assert dialog.dec_spin.value() == pytest.approx(41.412641, abs=1e-5)
    assert dialog.object_edit.text() == "M 31"
    assert dialog.binning_spin.value() == 1


def test_dialog_shows_the_users_real_plate_scale_and_field(qapp):
    dialog = OpticalWCSDialog((3008, 3008), _REAL_M31_HEADER)
    setup = dialog.current_setup()
    assert setup.pixel_scale_arcsec == pytest.approx(1.0355, abs=0.001)
    text = dialog.computed_label.text()
    assert "1.0355" in text
    assert "51.9'" in text  # 51.9 arcmin reales de campo
    assert dialog.warning_label.text() == ""  # todo coherente: sin avisos


def test_changing_the_camera_updates_the_pixel_size_and_warns_against_the_header(qapp):
    dialog = OpticalWCSDialog((3008, 3008), _REAL_M31_HEADER)
    dialog.camera_combo.setCurrentText("ZWO ASI294MC Pro")  # 4.63 µm, no es la del header
    assert dialog.pixel_spin.value() == pytest.approx(4.63)

    warning = dialog.warning_label.text()
    assert "cabecera" in warning
    assert "3.760" in warning  # lo que dice la cabecera real
    # y avisa además de que la geometría del sensor no es la de la imagen
    assert "4144" in warning


def test_half_size_image_is_flagged_as_a_superpixel_debayer(qapp):
    # una imagen demosaicada por SuperPixel mide la mitad: duplica la escala real
    dialog = OpticalWCSDialog((1504, 1504), _REAL_M31_HEADER)
    assert "SuperPixel" in dialog.warning_label.text()


def test_aperture_is_optional_and_never_invented(qapp):
    dialog = OpticalWCSDialog((3008, 3008), _REAL_M31_HEADER)
    assert dialog.current_setup().focal_ratio is None
    assert "f/" not in dialog.computed_label.text()

    dialog.aperture_spin.setValue(150.0)
    assert dialog.current_setup().focal_ratio == pytest.approx(749.0 / 150.0, rel=1e-6)
    assert "f/5.0" in dialog.computed_label.text()


def test_binning_doubles_the_scale_shown(qapp):
    dialog = OpticalWCSDialog((3008, 3008), _REAL_M31_HEADER)
    single = dialog.current_setup().pixel_scale_arcsec
    dialog.binning_spin.setValue(2)
    assert dialog.current_setup().pixel_scale_arcsec == pytest.approx(2 * single, rel=1e-9)


def test_custom_camera_lets_the_user_enter_geometry_by_hand(qapp):
    dialog = OpticalWCSDialog((1000, 800), {})
    dialog.camera_combo.setCurrentText(CUSTOM_CAMERA_OPTION)
    dialog.pixel_spin.setValue(9.0)
    dialog.focal_spin.setValue(2000.0)
    setup = dialog.current_setup()
    assert setup.pixel_scale_arcsec == pytest.approx(0.928, abs=0.002)
    assert (setup.width_px, setup.height_px) == (800, 1000)  # geometría real de la imagen


def test_building_wires_a_real_wcs_into_the_window_and_the_session(qapp, main_window):
    data = np.full((3008, 3008), 100.0, dtype=np.float32)
    sub_window = main_window.add_image_window(data, "m31_real.fit", header=_REAL_M31_HEADER, source_path="/tmp/m31_real.fit")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    assert view.fitted_wcs_solution is None

    dialog = OpticalWCSDialog(view.data.shape, view.header, main_window)
    dialog.built.connect(lambda solution, setup, v=view: main_window._on_optical_wcs_built(v, solution, setup))
    dialog._on_build()
    qapp.processEvents()

    solution = view.fitted_wcs_solution
    assert solution is not None
    assert pixel_scale_of(solution) == pytest.approx(1.0355, abs=0.001)
    ra, dec = solution.pixel_to_sky(*solution.crpix_px)
    assert (ra, dec) == pytest.approx((11.087505, 41.412641), abs=1e-6)
    # solución declarada, no ajustada: los informes deben poder distinguirlo
    assert is_optical_wcs(solution) is True
    # y queda en la sesión, indexada por la ruta real
    assert main_window.session_state.wcs_solutions["/tmp/m31_real.fit"] is solution


def test_menu_action_warns_without_an_open_image(qapp, main_window):
    main_window._open_optical_wcs_dialog()
    assert "imagen" in main_window.statusBar().currentMessage()
