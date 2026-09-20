"""Corrección real de absorción telúrica (§46) -- diálogo dedicado (menú
Espectroscopía) sobre `astrophysics_suite.spectroscopy.telluric_
correction`.

Dos ventanas reales, ambas ya calibradas en longitud de onda: la de la
estrella estándar telúrica (normalmente una A0V u otra estrella caliente
de continuo suave, cuentas/ADU) y la científica a corregir. La masa de
aire de cada una se toma de la cabecera real (`AIRMASS`) cuando existe, o
el usuario la da a mano -- nunca se asume `1.0` en silencio. La
corrección SOLO se aplica dentro de bandas telúricas catalogadas
realmente cubiertas por la estándar (§46: "nunca eliminar automáticamente
sin mostrar qué corrección se aplicó") -- la tabla muestra exactamente
qué bandas se usaron y el factor de corrección real aplicado.
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
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.spectrum1d_io import save_spectrum1d_fits
from astrophysics_suite.spectroscopy.telluric_correction import (
    TelluricCorrectionResult,
    TelluricStandardTransmission,
    correct_telluric_absorption,
    measure_standard_transmission,
)
from astrophysics_suite.tables.table import Table


def _central_row_spectrum(view) -> tuple[np.ndarray, np.ndarray]:
    row_index = view.data.shape[0] // 2
    counts = view.data[row_index, :].astype(np.float64)
    pixel = np.arange(counts.size, dtype=np.float64)
    wavelength = np.asarray(view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
    return wavelength, counts


def _header_airmass(view) -> float | None:
    if not view.header:
        return None
    value = view.header.get("AIRMASS")
    if value is None:
        return None
    try:
        airmass = float(value)
    except (TypeError, ValueError):
        return None
    return airmass if airmass > 0 else None


class TelluricCorrectionDialog(QDialog):
    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self._transmission: TelluricStandardTransmission | None = None
        self._last_result: TelluricCorrectionResult | None = None
        self._last_science_wavelength: np.ndarray | None = None
        self.setWindowTitle("Corrección de absorción telúrica")
        self.resize(640, 560)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Divide el espectro científico por la transmisión atmosférica REAL medida en una estrella estándar "
            "telúrica (continuo dividido por su propio ajuste), escalada por la razón de masas de aire -- solo "
            "dentro de las bandas telúricas catalogadas que la estándar cubre (§46). Nunca se aplica fuera de esas "
            "bandas, para no confundir líneas propias de la estándar con atmósfera."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.standard_combo = QComboBox()
        self.standard_combo.addItems(list(views))
        form.addRow("Ventana de la estándar telúrica", self.standard_combo)
        self.science_combo = QComboBox()
        self.science_combo.addItems(list(views))
        form.addRow("Ventana científica a corregir", self.science_combo)
        self.standard_airmass_spin = QDoubleSpinBox()
        self.standard_airmass_spin.setRange(1.0, 10.0)
        self.standard_airmass_spin.setDecimals(3)
        self.standard_airmass_spin.setValue(1.0)
        form.addRow("Masa de aire (estándar)", self.standard_airmass_spin)
        self.science_airmass_spin = QDoubleSpinBox()
        self.science_airmass_spin.setRange(1.0, 10.0)
        self.science_airmass_spin.setDecimals(3)
        self.science_airmass_spin.setValue(1.0)
        form.addRow("Masa de aire (científica)", self.science_airmass_spin)
        layout.addLayout(form)

        self.standard_combo.currentTextChanged.connect(self._prefill_standard_airmass)
        self.science_combo.currentTextChanged.connect(self._prefill_science_airmass)
        self._prefill_standard_airmass(self.standard_combo.currentText())
        self._prefill_science_airmass(self.science_combo.currentText())

        self.measure_button = QPushButton("Medir transmisión de la estándar")
        self.measure_button.clicked.connect(self._on_measure_standard)
        layout.addWidget(self.measure_button)

        self.apply_button = QPushButton("Aplicar corrección")
        self.apply_button.clicked.connect(self._on_apply)
        layout.addWidget(self.apply_button)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Banda telúrica", "Especie", "Rango (Å)"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.save_button = QPushButton("Guardar espectro corregido (FITS)...")
        self.save_button.clicked.connect(self._on_save)
        layout.addWidget(self.save_button)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    def _prefill_standard_airmass(self, title: str) -> None:
        view = self._views.get(title)
        airmass = _header_airmass(view) if view else None
        if airmass is not None:
            self.standard_airmass_spin.setValue(airmass)

    def _prefill_science_airmass(self, title: str) -> None:
        view = self._views.get(title)
        airmass = _header_airmass(view) if view else None
        if airmass is not None:
            self.science_airmass_spin.setValue(airmass)

    def _on_measure_standard(self) -> None:
        standard_view = self._views.get(self.standard_combo.currentText())
        if standard_view is None or standard_view.fitted_wavelength_solution is None:
            self.status_label.setText("La ventana de la estándar necesita una calibración en longitud de onda ajustada.")
            return
        wavelength, counts = _central_row_spectrum(standard_view)
        try:
            self._transmission = measure_standard_transmission(wavelength, counts)
        except ValueError as exc:
            self.status_label.setText(f"No se pudo medir la transmisión: {exc}")
            self._transmission = None
            return
        self.status_label.setText(
            f"Transmisión medida: {wavelength.size} punto(s) reales, RMS del continuo "
            f"{self._transmission.continuum_rms_residual:.4g}."
        )

    def _on_apply(self) -> None:
        if self._transmission is None:
            self.status_label.setText("Mide primero la transmisión de la estándar.")
            return
        science_view = self._views.get(self.science_combo.currentText())
        if science_view is None or science_view.fitted_wavelength_solution is None:
            self.status_label.setText("La ventana científica necesita una calibración en longitud de onda ajustada.")
            return

        wavelength, flux = _central_row_spectrum(science_view)
        try:
            self._last_result = correct_telluric_absorption(
                wavelength, flux, standard_transmission=self._transmission,
                science_airmass=self.science_airmass_spin.value(),
                standard_airmass=self.standard_airmass_spin.value(),
            )
        except ValueError as exc:
            self.status_label.setText(f"No se pudo aplicar la corrección: {exc}")
            self._last_result = None
            return
        self._last_science_wavelength = wavelength

        result = self._last_result
        self.table.setRowCount(len(result.bands_used))
        for row, band in enumerate(result.bands_used):
            self.table.setItem(row, 0, QTableWidgetItem(band.name))
            self.table.setItem(row, 1, QTableWidgetItem(band.species))
            self.table.setItem(
                row, 2, QTableWidgetItem(f"{band.wavelength_start_angstrom:.1f}-{band.wavelength_end_angstrom:.1f}")
            )

        n_corrected = int(np.count_nonzero(result.corrected_mask))
        self.status_label.setText(
            f"Corrección aplicada: {len(result.bands_used)} banda(s), {n_corrected} píxel(es) real(es) corregido(s) "
            f"(razón de masas de aire = {result.airmass_ratio:.3f}). Fuera de esas bandas el espectro no cambia."
        )

    def _on_save(self) -> None:
        if self._last_result is None or self._last_science_wavelength is None:
            self.status_label.setText("Aplica primero la corrección.")
            return
        science_view = self._views.get(self.science_combo.currentText())
        if science_view.wavelength_calibration_record is None:
            self.status_label.setText(
                f"{science_view.title} no tiene un registro de calibración en longitud de onda completo -- "
                "vuelve a calibrarla con \"Calibrar longitud de onda...\" antes de guardar."
            )
            return

        default_path = ""
        if science_view.source_path:
            from pathlib import Path

            source = Path(science_view.source_path)
            default_path = str(source.with_name(f"{source.stem}_tellcorr.fits"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar espectro corregido de telúricas", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return

        standard_view = self._views.get(self.standard_combo.currentText())
        extra_header = dict(science_view.header) if science_view.header else {}
        extra_header.update({
            "TELLCORR": True,
            "TELLSTD": standard_view.title if standard_view is not None else "",
            "TELLAIRS": float(self.science_airmass_spin.value()),
            "TELLAIRT": float(self.standard_airmass_spin.value()),
            "TELLNBND": len(self._last_result.bands_used),
        })
        try:
            save_spectrum1d_fits(
                path, self._last_result.corrected_flux, science_view.wavelength_calibration_record,
                header=extra_header,
            )
        except (ValueError, OSError) as exc:
            self.status_label.setText(f"No se pudo guardar «{path}»: {exc}")
            return
        self.status_label.setText(f"Espectro corregido de telúricas guardado en {path}.")

    def result_table(self) -> Table | None:
        if self._last_result is None:
            return None
        return Table(
            columns=("band_name", "species", "wavelength_start", "wavelength_end"),
            units=("", "", "Å", "Å"),
            rows=tuple(
                (band.name, band.species, band.wavelength_start_angstrom, band.wavelength_end_angstrom)
                for band in self._last_result.bands_used
            ),
        )
