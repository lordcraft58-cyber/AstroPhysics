"""Corrección de flexión/deriva espectral entre exposiciones (§44) --
diálogo dedicado (menú Espectroscopía) sobre `astrophysics_suite.
spectroscopy.flexure_correction`.

Dos ventanas reales: la de REFERENCIA (ya calibrada en longitud de onda,
`fitted_wavelength_solution` + `wavelength_calibration_record` reales) y
la NUEVA exposición (misma configuración instrumental, sin necesitar su
propia calibración -- se le aplica la de referencia, con solo el
desplazamiento global recalculado). El resultado se marca siempre
`offset_only_reidentified=True` (mismo campo honesto de §12/Slice 3):
nunca se presenta como una calibración recién medida por líneas.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.flexure_correction import FlexureShift, measure_flexure_shift
from astrophysics_suite.spectroscopy.spectrum1d_io import save_spectrum1d_fits
from astrophysics_suite.tables.table import Table
from qt_app.spectroscopy.spectrum_plot_data import SpectrumPlotData, SpectrumSeries, series_color


def _central_row_pixels(view) -> np.ndarray:
    """Fila central en ADU crudo, sin ningún eje de longitud de onda --
    la correlación cruzada de la deriva opera en píxeles, antes de saber
    si la ventana nueva tiene su propia calibración."""
    row_index = view.data.shape[0] // 2
    return view.data[row_index, :].astype(np.float64)


class FlexureCorrectionDialog(QDialog):
    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self._last_result: FlexureShift | None = None
        self.setWindowTitle("Corrección de flexión espectral entre exposiciones")
        self.resize(560, 380)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Mide el desplazamiento REAL (Δpíxel/Δλ/Δvelocidad) entre dos exposiciones de la misma configuración "
            "instrumental por correlación cruzada -- nunca recalcula el polinomio completo de la calibración, solo "
            "el desplazamiento global (§44). Útil con dos espectros de arco, o con cualquier par que comparta una "
            "referencia de posición fija (líneas telúricas reales, o un canal de calibración lateral)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.reference_combo = QComboBox()
        self.reference_combo.addItems(list(views))
        form.addRow("Ventana de referencia (ya calibrada)", self.reference_combo)
        self.new_combo = QComboBox()
        self.new_combo.addItems(list(views))
        form.addRow("Ventana nueva (misma configuración)", self.new_combo)
        self.reference_wavelength_spin = QDoubleSpinBox()
        self.reference_wavelength_spin.setRange(0.0, 100000.0)
        self.reference_wavelength_spin.setDecimals(2)
        self.reference_wavelength_spin.setValue(5500.0)
        form.addRow("Longitud de onda de referencia (Å)", self.reference_wavelength_spin)
        layout.addLayout(form)

        self.reference_combo.currentTextChanged.connect(self._prefill_reference_wavelength)
        self._prefill_reference_wavelength(self.reference_combo.currentText())

        self.measure_button = QPushButton("Medir desplazamiento")
        self.measure_button.clicked.connect(self._on_measure)
        layout.addWidget(self.measure_button)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.compare_button = QPushButton("Ver comparación antes/después...")
        self.compare_button.clicked.connect(self._on_show_comparison)
        layout.addWidget(self.compare_button)

        self.save_button = QPushButton("Aplicar y guardar espectro corregido (FITS)...")
        self.save_button.clicked.connect(self._on_save)
        layout.addWidget(self.save_button)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    def _prefill_reference_wavelength(self, title: str) -> None:
        view = self._views.get(title)
        if view is None or view.fitted_wavelength_solution is None:
            return
        pixel = np.arange(view.data.shape[1], dtype=np.float64)
        wavelength = np.asarray(view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
        self.reference_wavelength_spin.setValue(float(np.median(wavelength)))

    def _on_measure(self) -> None:
        reference_view = self._views.get(self.reference_combo.currentText())
        new_view = self._views.get(self.new_combo.currentText())
        if reference_view is None or new_view is None:
            self.result_label.setText("Elige dos ventanas reales.")
            return
        if reference_view.fitted_wavelength_solution is None:
            self.result_label.setText(
                f"{reference_view.title} no tiene una calibración en longitud de onda ajustada todavía -- "
                "usa antes \"Calibrar longitud de onda...\"."
            )
            return

        reference_spectrum = _central_row_pixels(reference_view)
        new_spectrum = _central_row_pixels(new_view)
        if reference_spectrum.shape != new_spectrum.shape:
            self.result_label.setText(
                f"{reference_view.title} y {new_view.title} tienen anchos distintos "
                f"({reference_spectrum.size} vs {new_spectrum.size} px) -- no son la misma configuración instrumental."
            )
            return

        try:
            self._last_result = measure_flexure_shift(
                reference_view.fitted_wavelength_solution, reference_spectrum, new_spectrum,
                reference_wavelength=self.reference_wavelength_spin.value(),
            )
        except ValueError as exc:
            self.result_label.setText(f"No se pudo medir el desplazamiento: {exc}")
            self._last_result = None
            return

        result = self._last_result
        self.result_label.setText(
            f"Δpíxel = {result.shift_px:+.3f} px  ·  Δλ = {result.shift_angstrom:+.3f} Å (en "
            f"{result.reference_wavelength:.1f} Å)  ·  Δv = {result.shift_velocity_km_s:+.2f} km/s -- "
            "solo se recalculó el desplazamiento global, la forma de la calibración no cambia."
        )

    def _on_show_comparison(self) -> None:
        if self._last_result is None:
            self.result_label.setText("Mide primero el desplazamiento.")
            return
        reference_view = self._views.get(self.reference_combo.currentText())
        new_view = self._views.get(self.new_combo.currentText())
        reference_spectrum = _central_row_pixels(reference_view)
        new_spectrum = _central_row_pixels(new_view)

        pixel = np.arange(new_spectrum.size, dtype=np.float64)
        reference_wavelength = np.asarray(reference_view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
        # "sin corregir" == la solución ORIGINAL de la referencia, sin el
        # desplazamiento real medido -- exactamente lo que se vería si no
        # se hubiera aplicado esta corrección.
        after_wavelength = np.asarray(self._last_result.shifted_solution.pixel_to_wavelength(pixel), dtype=np.float64)

        plot_data = SpectrumPlotData(
            series=(
                SpectrumSeries(
                    label=f"Referencia ({reference_view.title})", x=reference_wavelength, y=reference_spectrum,
                    color=series_color(0),
                ),
                SpectrumSeries(
                    label=f"Nueva SIN corregir ({new_view.title})", x=reference_wavelength, y=new_spectrum,
                    color=series_color(1), style="dashed",
                ),
                SpectrumSeries(
                    label=f"Nueva corregida ({new_view.title})", x=after_wavelength, y=new_spectrum,
                    color=series_color(2),
                ),
            ),
            x_label="Longitud de onda (Å)", y_label="Cuentas (ADU)", x_unit="Å",
        )
        main_window = self.parent()
        if main_window is None or not hasattr(main_window, "add_spectrum_window"):
            self.result_label.setText("No se pudo abrir la comparación (ventana principal no disponible).")
            return
        main_window.add_spectrum_window(plot_data, f"Antes/después -- {new_view.title}")

    def _on_save(self) -> None:
        if self._last_result is None:
            self.result_label.setText("Mide primero el desplazamiento.")
            return
        reference_view = self._views.get(self.reference_combo.currentText())
        new_view = self._views.get(self.new_combo.currentText())
        base_record = reference_view.wavelength_calibration_record
        if base_record is None:
            self.result_label.setText(
                f"{reference_view.title} no tiene un registro de calibración completo -- vuelve a calibrarla con "
                "\"Calibrar longitud de onda...\" antes de guardar."
            )
            return

        from dataclasses import replace

        record = replace(
            base_record, solution=self._last_result.shifted_solution, offset_only_reidentified=True,
        )
        new_spectrum = _central_row_pixels(new_view)

        default_path = ""
        if new_view.source_path:
            from pathlib import Path

            source = Path(new_view.source_path)
            default_path = str(source.with_name(f"{source.stem}_flexure_corregido.fits"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar espectro con flexión corregida", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return
        try:
            save_spectrum1d_fits(path, new_spectrum, record, header=dict(new_view.header) if new_view.header else None)
        except (ValueError, OSError) as exc:
            self.result_label.setText(f"No se pudo guardar «{path}»: {exc}")
            return
        new_view.fitted_wavelength_solution = record.solution
        new_view.wavelength_calibration_record = record
        new_view.wavelength_calibration_spectrum = new_spectrum
        self.result_label.setText(f"Espectro con flexión corregida guardado en {path}.")

    def result_table(self) -> Table | None:
        if self._last_result is None:
            return None
        result = self._last_result
        return Table(
            columns=("shift_px", "shift_angstrom", "shift_velocity_kms", "reference_wavelength"),
            units=("px", "Å", "km/s", "Å"),
            rows=((result.shift_px, result.shift_angstrom, result.shift_velocity_km_s, result.reference_wavelength),),
        )
