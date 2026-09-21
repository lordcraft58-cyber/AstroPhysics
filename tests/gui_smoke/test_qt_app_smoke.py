"""Prueba de humo del taller PixInsight/Qt (Fase 9.6): la ventana debe
construirse, cargar una imagen, y ejecutar un proceso real de principio
a fin (incluido el hilo de fondo) sin excepción -- el mismo nivel de
exigencia que `tests/gui_smoke/test_app_smoke.py` aplicó a la GUI en
Tkinter de la Fase 8.

Requiere PySide6 y un display X (real o Xvfb) -- si no están disponibles,
el test se salta en vez de fallar por una razón ajena al código bajo
prueba.
"""
from __future__ import annotations

import math
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


@pytest.fixture
def main_window(qapp):
    from qt_app.main_window import MainWindow

    window = MainWindow()
    yield window
    window.close()


def _synthetic_field(shape=(80, 80), seed=0):
    rng = np.random.default_rng(seed)
    data = 200.0 + rng.normal(0, 8.0, shape)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    data += 8000.0 / (2 * np.pi * 3.0**2) * np.exp(-(((xx - 40) ** 2 + (yy - 40) ** 2)) / (2 * 3.0**2))
    data[10, 60] += 20000.0  # rayo cósmico inyectado
    return data


def _run_process_and_wait(qapp, main_window, process_id: str, params: dict, timeout_s: float = 5.0):
    process = main_window._process_by_id[process_id]
    main_window._run_process(process_id, params)
    deadline = time.monotonic() + timeout_s
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()
    return process


def test_main_window_builds_without_exception(main_window):
    assert main_window.windowTitle().startswith("AstroPhysics Suite")
    assert main_window.mdi is not None
    assert len(main_window._processes) > 0


def test_process_explorer_lists_both_wired_and_unwired_processes(main_window):
    wired = [p for p in main_window._processes if p.is_wired]
    unwired = [p for p in main_window._processes if not p.is_wired]
    assert wired and unwired


def test_add_image_window_creates_mdi_subwindow(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "test.fits")
    qapp.processEvents()
    assert sub_window in main_window.mdi.subWindowList()
    assert sub_window.widget().data is data


def test_main_toolbar_exposes_the_most_frequent_actions_and_can_be_hidden(qapp, main_window):
    """Reorganización estilo PixInsight (Fase 22): barra de iconos para
    las acciones más frecuentes, con los mismos `QAction` de los menús
    (nunca duplicados) -- y se puede ocultar/mostrar desde Vista, como
    cualquier barra de herramientas real de Qt."""
    assert main_window.main_toolbar is not None
    toolbar_actions = set(main_window.main_toolbar.actions())
    for action in (
        main_window.open_action, main_window.new_observation_action, main_window.cancel_discovery_action,
        main_window.plate_solve_action, main_window.build_master_action, main_window.apply_calibration_action,
        main_window.stf_action,
    ):
        assert action in toolbar_actions
        assert not action.icon().isNull()

    main_window.show()
    qapp.processEvents()
    assert main_window.main_toolbar.isVisible()
    main_window.toggle_toolbar_action.trigger()
    assert not main_window.main_toolbar.isVisible()
    main_window.toggle_toolbar_action.trigger()
    assert main_window.main_toolbar.isVisible()


def test_pixel_readout_updates_on_mouse_move_over_image_and_shows_dashes_outside_bounds(qapp, main_window):
    """Lectura de píxel al estilo PixInsight ("Readout") en la barra de
    estado: posición + valor ADU real bajo el cursor, actualizado en
    tiempo real -- nunca un valor inventado fuera de los límites de la
    imagen."""
    yy, xx = np.mgrid[0:40, 0:40]
    data = (yy * 100 + xx).astype(np.float64)  # cada píxel tiene un valor único y predecible
    sub_window = main_window.add_image_window(data, "readout_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    # `mapFromScene`/`mapToScene` recorren la transformación real de la
    # vista (que puede no ser 1:1 según centrado/scroll de
    # QGraphicsView) -- el valor esperado se deriva de la posición de
    # escena REALMENTE resuelta, con la misma conversión a índice entero
    # que usa la propia `ImageView.mouseMoveEvent`, en vez de asumir un
    # redondeo concreto.
    widget_pos = view.mapFromScene(10.0, 10.0)
    scene_pos = view.mapToScene(widget_pos)
    ix, iy = int(scene_pos.x()), int(scene_pos.y())
    assert 0 <= ix < 40 and 0 <= iy < 40, "la posición de prueba debe caer dentro de la imagen"
    expected_value = data[iy, ix]

    inside_event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(widget_pos), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(inside_event)
    qapp.processEvents()
    assert f"Valor: {expected_value:.2f}" in main_window.readout_label.text()

    widget_pos_outside = view.mapFromScene(-100.0, -100.0)
    outside_event = QMouseEvent(QMouseEvent.Type.MouseMove, QPointF(widget_pos_outside), Qt.MouseButton.NoButton, Qt.MouseButton.NoButton, Qt.KeyboardModifier.NoModifier)
    view.mouseMoveEvent(outside_event)
    qapp.processEvents()
    assert "Valor: --" in main_window.readout_label.text()


def test_running_cosmic_ray_process_creates_cleaned_output_window(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "cr_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    windows_before = len(main_window.mdi.subWindowList())
    default_params = {p.name: p.default for p in main_window._process_by_id["imtools.cosmic_rays"].parameters}
    _run_process_and_wait(qapp, main_window, "imtools.cosmic_rays", default_params)

    windows_after = main_window.mdi.subWindowList()
    assert len(windows_after) == windows_before + 1
    new_view = windows_after[-1].widget()
    assert abs(new_view.data[10, 60] - 200.0) < 100.0  # el pico inyectado debe haberse limpiado


def test_running_measurement_process_does_not_create_new_window(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "phot_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    windows_before = len(main_window.mdi.subWindowList())
    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.aperture"].parameters}
    main_window._run_process("photometry.aperture", default_params)
    qapp.processEvents()
    assert view._picking is True  # ahora pide marcar la fuente con un clic

    view_point = view.mapFromScene(QPointF(40.0, 40.0))
    event = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(view_point), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(event)  # un único clic: termina sola (requires_picking=1)
    qapp.processEvents()

    deadline = time.monotonic() + 5.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()

    assert len(main_window.mdi.subWindowList()) == windows_before


def test_aperture_photometry_auto_detect_skips_manual_picking_and_fits_curve_of_growth(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "auto_detect_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.aperture"].parameters}
    default_params["auto_detect"] = True
    default_params["fit_curve_of_growth"] = True
    default_params["sky_r_in"] = 20.0
    default_params["sky_r_out"] = 30.0
    default_params["detect_fwhm_px"] = 7.0  # FWHM real de la fuente inyectada por _synthetic_field (sigma=3.0 px)

    _run_process_and_wait(qapp, main_window, "photometry.aperture", default_params)

    assert view._picking is False  # nunca entró en modo de clic manual
    assert "completado" in main_window.statusBar().currentMessage().lower() or "detección" in main_window.statusBar().currentMessage().lower()
    assert main_window._last_result_table is not None
    assert main_window._last_result_table.columns == ("radius_px", "net_flux", "snr")


def test_aperture_photometry_auto_detect_reports_when_no_source_found(qapp, main_window):
    data = np.full((60, 60), 200.0)  # campo plano, sin fuentes por encima del umbral
    sub_window = main_window.add_image_window(data, "no_sources_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.aperture"].parameters}
    default_params["auto_detect"] = True

    main_window._run_process("photometry.aperture", default_params)
    qapp.processEvents()

    assert "ninguna fuente" in main_window.statusBar().currentMessage().lower()
    assert main_window._active_worker is None


def test_zeropoint_auto_detect_measures_multiple_stars_without_clicks(qapp, main_window, monkeypatch):
    import math

    from astropy.wcs import WCS

    import qt_app.processes.registry as registry_module

    shape = (101, 101)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    star_positions = [(30.0, 30.0, 30000.0), (70.0, 60.0, 20000.0)]
    data = np.full(shape, 150.0)
    sigma = 2.2
    for x0, y0, flux in star_positions:
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [50.0, 50.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    true_zeropoint = 24.0
    gaia_rows = []
    for x0, y0, flux in star_positions:
        ra, dec = wcs.celestial.all_pix2world(x0, y0, 0)
        instrumental_mag = -2.5 * math.log10(flux)
        gaia_rows.append({"ra_deg": float(ra), "dec_deg": float(dec), "mag_g": instrumental_mag + true_zeropoint, "source_id": f"{x0}-{y0}"})
    monkeypatch.setattr(registry_module, "query_gaia_neighbors", lambda ra, dec, **kwargs: gaia_rows)

    sub_window = main_window.add_image_window(data, "zeropoint_auto_test.fits", wcs=wcs)
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.zeropoint"].parameters}
    default_params["auto_detect"] = True

    _run_process_and_wait(qapp, main_window, "photometry.zeropoint", default_params)

    assert view._picking is False  # nunca entró en modo de clic manual
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == len(star_positions)


def test_psf_auto_detect_selects_isolated_stars_and_skips_close_pair(qapp, main_window):
    shape = (150, 150)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    sigma = 2.0
    data = np.full(shape, 150.0)
    # dos estrellas aisladas (deben seleccionarse) + un par pegado (debe rechazarse por falta de aislamiento)
    isolated_positions = [(30.0, 30.0, 25000.0), (110.0, 40.0, 20000.0)]
    close_pair = [(70.0, 100.0, 15000.0), (76.0, 100.0, 15000.0)]
    for x0, y0, flux in isolated_positions + close_pair:
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    sub_window = main_window.add_image_window(data, "psf_auto_detect_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.psf"].parameters}
    default_params["auto_detect"] = True
    default_params["detect_fwhm_px"] = 2.0 * math.sqrt(2 * math.log(2)) * sigma
    default_params["psf_min_separation_px"] = 15.0

    _run_process_and_wait(qapp, main_window, "photometry.psf", default_params)

    assert view._picking is False  # nunca entró en modo de clic manual
    assert main_window._last_result_table is not None
    assert len(main_window._last_result_table.rows) == len(isolated_positions)  # el par pegado quedó fuera


def test_psf_position_refinement_and_diagnostics_run_end_to_end_via_click(qapp, main_window):
    sigma = 2.0
    true_flux = 30000.0
    true_x, true_y = 30.4, 29.6
    yy, xx = np.mgrid[0:61, 0:61]
    data = 150.0 + true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - true_x) ** 2 + (yy - true_y) ** 2)) / (2 * sigma**2))

    sub_window = main_window.add_image_window(data, "psf_refine_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()

    default_params = {p.name: p.default for p in main_window._process_by_id["photometry.psf"].parameters}
    default_params["sigma_px"] = sigma
    default_params["refine_positions"] = True
    default_params["report_fit_diagnostics"] = True

    windows_before = len(main_window.mdi.subWindowList())
    main_window._run_process("photometry.psf", default_params)
    qapp.processEvents()
    assert view._picking is True

    # clic deliberadamente descentrado -- el refinamiento debe converger a la posición real
    click_point = view.mapFromScene(QPointF(true_x + 1.4, true_y - 1.1))
    left_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(click_point), Qt.MouseButton.LeftButton, Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(left_click)  # marca la posición (descentrada a propósito)
    qapp.processEvents()
    finish_point = view.mapFromScene(QPointF(0.0, 0.0))
    right_click = QMouseEvent(
        QMouseEvent.Type.MouseButtonPress, QPointF(finish_point), Qt.MouseButton.RightButton, Qt.MouseButton.RightButton, Qt.KeyboardModifier.NoModifier
    )
    view.mousePressEvent(right_click)  # clic derecho: termina la selección ilimitada
    qapp.processEvents()

    deadline = time.monotonic() + 10.0
    while main_window._active_worker is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.02)
    qapp.processEvents()

    assert len(main_window.mdi.subWindowList()) == windows_before + 1  # imagen de residuo del diagnóstico
    assert main_window._last_result_table is not None
    refined_x, refined_y = main_window._last_result_table.rows[0][0], main_window._last_result_table.rows[0][1]
    assert refined_x == pytest.approx(true_x, abs=0.2)
    assert refined_y == pytest.approx(true_y, abs=0.2)


def test_running_process_without_active_image_reports_status_and_does_not_crash(qapp, main_window):
    for sub_window in list(main_window.mdi.subWindowList()):
        sub_window.close()
    qapp.processEvents()

    default_params = {p.name: p.default for p in main_window._process_by_id["imtools.cosmic_rays"].parameters}
    main_window._run_process("imtools.cosmic_rays", default_params)
    assert "imagen" in main_window.statusBar().currentMessage().lower()


def test_process_dropped_on_view_selects_it_in_properties(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "drop_test.fits")
    qapp.processEvents()
    view = sub_window.widget()

    main_window._on_process_dropped("photometry.aperture", view)
    qapp.processEvents()

    assert main_window.mdi.activeSubWindow() is sub_window
    assert main_window.properties.current_process is main_window._process_by_id["photometry.aperture"]


def test_stf_toggle_does_not_raise(qapp, main_window):
    data = _synthetic_field()
    sub_window = main_window.add_image_window(data, "stf_test.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    view = sub_window.widget()
    assert view.stf_enabled is True
    main_window._toggle_active_stf()
    assert view.stf_enabled is False
    main_window._toggle_active_stf()
    assert view.stf_enabled is True


def test_open_fits_with_bzero_bscale_file_succeeds(qapp, main_window, tmp_path):
    """Regresión: astropy no podía memory-mapear un HDU con BZERO/BSCALE (la
    convención estándar de casi cualquier cámara CCD/CMOS de 16 bits) y
    `open_fits` no capturaba el fallo -- ver el fix en
    legacy...load_fits y tests/unit/io/test_fits_loader.py."""
    from astropy.io import fits

    raw_values = np.arange(400, dtype=np.uint16).reshape(20, 20) + 1000
    path = tmp_path / "camera_16bit.fits"
    fits.PrimaryHDU(raw_values).writeto(path)

    sub_window = main_window.open_fits(str(path))
    qapp.processEvents()

    assert sub_window is not None
    assert sub_window in main_window.mdi.subWindowList()
    np.testing.assert_array_equal(sub_window.widget().data.astype(np.uint16), raw_values)


def test_open_3d_fits_prompts_for_plane_and_opens_correct_slice(qapp, main_window, tmp_path, monkeypatch):
    """Bug real reportado en uso: "no me deja abrir imágenes de 3
    dimensiones". `load_fits` se niega deliberadamente a elegir un plano
    por su cuenta (`AmbiguousCubeError`) -- antes de este flujo, eso
    significaba que un FITS 3D/4D simplemente no se podía abrir nunca
    desde la GUI. Ahora `open_fits` captura la excepción y pide el índice
    con `CubePlaneDialog`."""
    from astropy.io import fits

    from qt_app.io.cube_plane_dialog import CubePlaneDialog

    cube = np.arange(5 * 24 * 24, dtype=np.float32).reshape(5, 24, 24)
    path = tmp_path / "cube_HA.fits"
    fits.PrimaryHDU(cube).writeto(path)

    captured = {}
    original_exec = CubePlaneDialog.exec

    def _capture_and_accept(self):
        captured["shape"] = self._extra_axes
        for spin in self._spinboxes:
            spin.setValue(3)  # elige el plano 3 de 5, a propósito distinto del 0 por defecto
        return CubePlaneDialog.DialogCode.Accepted

    CubePlaneDialog.exec = _capture_and_accept
    try:
        sub_window = main_window.open_fits(str(path))
        qapp.processEvents()
    finally:
        CubePlaneDialog.exec = original_exec

    assert captured["shape"] == 1  # un solo eje sobrante para un cubo 3D
    assert sub_window is not None
    assert sub_window in main_window.mdi.subWindowList()
    np.testing.assert_array_equal(sub_window.widget().data, cube[3])
    assert "plano" in sub_window.windowTitle().lower()


def test_open_3d_fits_cancelled_at_plane_dialog_opens_no_window(qapp, main_window, tmp_path):
    from astropy.io import fits

    from qt_app.io.cube_plane_dialog import CubePlaneDialog

    cube = np.zeros((4, 20, 20), dtype=np.float32)
    path = tmp_path / "cube_cancel.fits"
    fits.PrimaryHDU(cube).writeto(path)

    windows_before = len(main_window.mdi.subWindowList())
    original_exec = CubePlaneDialog.exec
    CubePlaneDialog.exec = lambda self: CubePlaneDialog.DialogCode.Rejected
    try:
        result = main_window.open_fits(str(path))
        qapp.processEvents()
    finally:
        CubePlaneDialog.exec = original_exec

    assert result is None
    assert len(main_window.mdi.subWindowList()) == windows_before


def _write_minimal_xisf(path, data: np.ndarray, *, fits_keywords: dict[str, str] | None = None) -> None:
    """Mismo formato real que `tests/unit/io/test_fits_loader_xisf.py`
    (construido byte a byte, verificado ahí contra una herramienta de
    desarrollo independiente) -- reproducido aquí para probar el
    despacho de VERDAD desde la GUI (`open_fits`), no solo desde
    `io.fits_loader.load_image` a nivel de unidad."""
    import struct

    height, width = data.shape
    sample_format = {np.dtype("uint16"): "UInt16", np.dtype("float32"): "Float32"}[data.dtype]
    raw = data.tobytes()
    placeholder = "0" * 12
    kw_xml = "".join(f'<FITSKeyword name="{k}" value="{v}" comment="" />' for k, v in (fits_keywords or {}).items())
    xml = (
        f'<?xml version="1.0" encoding="utf8"?>'
        f'<xisf xmlns="http://www.pixinsight.com/xisf" version="1.0">'
        f'<Image id="image" geometry="{width}:{height}:1" colorSpace="Gray" sampleFormat="{sample_format}" '
        f'location="attachment:{placeholder}:{len(raw)}">{kw_xml}</Image></xisf>'
    )
    xml_bytes = xml.encode("utf-8")
    data_offset = 16 + len(xml_bytes)
    real_offset_str = str(data_offset).zfill(len(placeholder))
    xml_bytes = xml_bytes.replace(placeholder.encode("ascii"), real_offset_str.encode("ascii"), 1)
    with open(path, "wb") as f:
        f.write(b"XISF0100")
        f.write(struct.pack("<I", len(xml_bytes)))
        f.write(b"\x00\x00\x00\x00")
        f.write(xml_bytes)
        f.write(raw)


def test_open_fits_opens_a_real_xisf_file_through_the_same_gui_flow(qapp, main_window, tmp_path):
    # `open_fits_dialog` lista *.xisf en su filtro nativo junto a FITS,
    # pero ningún test de humo GUI había abierto uno de verdad por el
    # flujo real (`main_window.open_fits`) -- solo a nivel de unidad
    # (`io.fits_loader.load_image`). Cierra ese hueco de cobertura.
    rng = np.random.default_rng(11)
    data = rng.integers(2800, 5000, size=(30, 40), dtype=np.uint16)
    path = tmp_path / "field.xisf"
    _write_minimal_xisf(path, data, fits_keywords={"OBJECT": "'M 31'", "EXPTIME": "300.0"})

    sub_window = main_window.open_fits(str(path))
    qapp.processEvents()

    assert sub_window is not None
    assert sub_window in main_window.mdi.subWindowList()
    np.testing.assert_array_equal(sub_window.widget().data.astype(np.uint16), data)
    assert sub_window.widget().header.get("OBJECT") == "M 31"


def test_open_fits_shows_error_dialog_instead_of_failing_silently(qapp, main_window, tmp_path, monkeypatch):
    from qt_app import main_window as main_window_module

    bad_path = tmp_path / "not_a_real_fits.fits"
    bad_path.write_bytes(b"not a fits file")

    shown = {}
    monkeypatch.setattr(
        main_window_module.QMessageBox, "critical", lambda *args, **kwargs: shown.update(called=True)
    )

    windows_before = len(main_window.mdi.subWindowList())
    result = main_window.open_fits(str(bad_path))
    qapp.processEvents()

    assert result is None
    assert shown.get("called") is True
    assert len(main_window.mdi.subWindowList()) == windows_before


def test_diagnostics_dialog_runs_hardware_check_end_to_end(qapp, main_window):
    from qt_app.diagnostics_dialog import DiagnosticsDialog

    dialog = DiagnosticsDialog(main_window)
    dialog._run()
    assert not dialog.run_button.isEnabled()

    deadline = time.monotonic() + 5.0
    while dialog._job is not None and time.monotonic() < deadline:
        qapp.processEvents()
        time.sleep(0.01)
    qapp.processEvents()

    assert dialog._job is None
    assert dialog.run_button.isEnabled()
