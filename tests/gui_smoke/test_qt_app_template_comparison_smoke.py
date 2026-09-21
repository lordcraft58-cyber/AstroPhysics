"""Prueba de humo de extremo a extremo de la comparación con plantilla
de referencia (§25): carga real de una plantilla FITS 1D + comparación
contra la ventana observada -- abre una ventana de espectro nueva con
observado/plantilla/residuo real, sin clasificar nada.

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

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
    window.show()
    qapp.processEvents()
    yield window
    window.close()


_TRUE_PIXELS = (40.0, 110.0, 190.0, 260.0)
_TRUE_WAVELENGTHS = (4046.6, 4358.3, 5460.7, 5769.6)


def _synthetic_arc_row(width=300, height=21):
    row = np.full(width, 100.0)
    for pixel in _TRUE_PIXELS:
        idx = int(round(pixel))
        row[idx - 2 : idx + 3] += [50, 400, 1200, 400, 50]
    return np.tile(row, (height, 1))


def test_template_comparison_dialog_compares_a_real_window_against_a_saved_template(qapp, main_window, tmp_path):
    from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
    from astrophysics_suite.spectroscopy.spectrum1d_io import save_spectrum1d_fits
    from qt_app.spectroscopy.template_comparison_dialog import TemplateComparisonDialog
    from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "arc_for_template.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()

    def _fill_and_fit(self):
        for row in range(self.table.rowCount()):
            self.table.item(row, 2).setText(str(_TRUE_WAVELENGTHS[row]))
        self._on_fit()
        return WavelengthFitDialog.DialogCode.Accepted

    original_exec = WavelengthFitDialog.exec
    WavelengthFitDialog.exec = _fill_and_fit
    try:
        main_window._open_wavelength_fit_flow()
        qapp.processEvents()
    finally:
        WavelengthFitDialog.exec = original_exec

    view = sub_window.widget()
    assert view.fitted_wavelength_solution is not None

    # plantilla real: el MISMO espectro observado, guardado como FITS 1D real
    template_path = tmp_path / "template.fits"
    record = WavelengthCalibrationRecord(solution=view.fitted_wavelength_solution, source=CalibrationSource.LAMP_REAL, n_lines_used=4, lamp_name="Ne")
    row_index = data.shape[0] // 2
    save_spectrum1d_fits(str(template_path), data[row_index, :].astype(float), record)

    windows_before = len(main_window.mdi.subWindowList())
    dialog = TemplateComparisonDialog(main_window._image_views_by_title(), main_window)
    dialog._template_path = str(template_path)
    from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits

    wavelength, flux, _header = load_spectrum1d_fits(str(template_path))
    dialog._template_wavelength = wavelength
    dialog._template_flux = flux
    dialog.normalize_combo.setCurrentText("none")
    dialog._on_compare()

    assert "Solape real" in dialog.result_label.text()
    assert len(main_window.mdi.subWindowList()) == windows_before + 1
    table = dialog.result_table()
    assert table is not None
    assert table.rows[0][0] == pytest.approx(1.0)  # mismo espectro: solape total real

    # el mismo espectro consigo mismo: residuo prácticamente cero
    result = dialog._last_result
    assert result is not None
    finite = np.isfinite(result.residual)
    np.testing.assert_allclose(result.residual[finite], 0.0, atol=1e-6)


def test_template_comparison_dialog_imports_an_ascii_template_and_can_compare_with_it(qapp, main_window, tmp_path):
    # §25 extendido: una plantilla real puede venir de un archivo de
    # texto de dos columnas (longitud de onda, flujo) -- formato en el
    # que suelen venir las bibliotecas espectrales externas -- sin tener
    # que convertirla a mano a FITS antes.
    from PySide6.QtWidgets import QFileDialog

    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.template_comparison_dialog import TemplateComparisonDialog

    ascii_path = tmp_path / "reference.ssp"
    lines = ["*SpHdr* REF-STAR,1.0,2.0,3.0"]
    for i in range(50):
        lines.append(f"{4000.0 + 2.0 * i:.2f} {0.5 + 0.01 * i:.5f}")
    ascii_path.write_text("\n".join(lines) + "\n")

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_ascii_template.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = TemplateComparisonDialog(main_window._image_views_by_title(), main_window)

    original_get_open = QFileDialog.getOpenFileName
    QFileDialog.getOpenFileName = staticmethod(lambda *args, **kwargs: (str(ascii_path), ""))
    try:
        dialog._on_import_ascii_template()
    finally:
        QFileDialog.getOpenFileName = original_get_open

    assert dialog._template_wavelength is not None
    assert dialog._template_wavelength.size == 50
    assert "importada de texto" in dialog.template_label.text()
    assert "REF-STAR" in dialog.template_label.text()

    dialog.normalize_combo.setCurrentText("median")
    dialog._on_compare()
    assert "Solape real" in dialog.result_label.text()


def test_template_comparison_dialog_loads_a_real_standard_from_the_bundled_jacoby_atlas(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.template_comparison_dialog import TemplateComparisonDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "target_for_atlas_template.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = TemplateComparisonDialog(main_window._image_views_by_title(), main_window)
    assert dialog.atlas_combo.count() == 161  # las 161 estrellas reales del atlas incluido
    assert dialog.atlas_combo.isEnabled()

    dialog.atlas_combo.setCurrentIndex(0)
    dialog._on_use_atlas_standard()

    assert dialog._template_wavelength is not None
    assert dialog._template_wavelength.min() == pytest.approx(3510.0, abs=1.0)
    assert "atlas Jacoby-Hunter-Christian" in dialog.template_label.text()

    dialog.normalize_combo.setCurrentText("median")
    dialog._on_compare()
    assert "Solape real" in dialog.result_label.text()


def test_template_comparison_dialog_requires_a_real_template_before_comparing(qapp, main_window):
    from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
    from qt_app.spectroscopy.template_comparison_dialog import TemplateComparisonDialog

    data = _synthetic_arc_row()
    sub_window = main_window.add_image_window(data, "no_template_yet.fits")
    main_window.mdi.setActiveSubWindow(sub_window)
    qapp.processEvents()
    view = sub_window.widget()
    # calibrada a mano (sin pasar por el diálogo de ajuste) -- lo único que
    # importa aquí es que YA tenga una solución real, para aislar el aviso
    # de "falta plantilla" del de "falta calibración".
    view.fitted_wavelength_solution = fit_wavelength_solution(list(_TRUE_PIXELS), list(_TRUE_WAVELENGTHS), degree=1)

    dialog = TemplateComparisonDialog(main_window._image_views_by_title(), main_window)
    dialog._on_compare()
    assert "plantilla" in dialog.result_label.text().lower()
