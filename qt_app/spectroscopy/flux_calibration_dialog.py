"""Calibración de flujo absoluta desde una estrella estándar (§48) --
diálogo dedicado (menú Espectroscopía) sobre `astrophysics_suite.
spectroscopy.fluxcal` (ya existente y probado desde la Fase 9.5/18,
pero sin cablear en la GUI hasta ahora -- ver informe 61 §5).

Dos ventanas reales, ambas YA calibradas en longitud de onda: la de la
estrella estándar (cuentas/ADU) y la científica a calibrar. La
referencia física de la estándar se carga siempre de un archivo CALSPEC
real (`standard_stars.load_calspec_spectrum`) -- nunca inventada. La
masa de aire se toma de la cabecera real (`AIRMASS`) cuando existe, o el
usuario la da a mano -- nunca se asume `1.0` en silencio. El resultado
se guarda como un FITS 1D real con `BUNIT` físico y la procedencia
completa (estándar usada, grado del ajuste, masa de aire, coeficiente de
extinción) en HISTORY -- nunca sobrescribe el espectro original ni llama
"calibración" a lo que en realidad sería solo un reescalado.
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
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.fluxcal import SensitivityFunction, build_sensitivity_function, calibrate_flux
from astrophysics_suite.spectroscopy.spectrum1d_io import save_spectrum1d_fits
from astrophysics_suite.spectroscopy.standard_stars import CALSPEC_STANDARD_STARS, load_calspec_spectrum
from astrophysics_suite.tables.table import Table

_NO_REFERENCE = "(sin especificar)"


def _central_row_counts(view) -> tuple[np.ndarray, np.ndarray]:
    """Fila central como espectro 1D en longitud de onda -- misma
    convención que el resto de diálogos de espectroscopía."""
    row_index = view.data.shape[0] // 2
    counts = view.data[row_index, :].astype(np.float64)
    pixel = np.arange(counts.size, dtype=np.float64)
    wavelength = np.asarray(view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
    return wavelength, counts


def _header_exptime(view) -> float | None:
    if not view.header:
        return None
    for key in ("EXPTIME", "EXPOSURE"):
        value = view.header.get(key)
        if value is not None:
            try:
                exptime = float(value)
            except (TypeError, ValueError):
                continue
            if exptime > 0:
                return exptime
    return None


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


class FluxCalibrationDialog(QDialog):
    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self._reference_wavelength: np.ndarray | None = None
        self._reference_flux: np.ndarray | None = None
        self._reference_path: str | None = None
        self._sensitivity: SensitivityFunction | None = None
        self._last_calibrated_wavelength: np.ndarray | None = None
        self._last_calibrated_flux: np.ndarray | None = None
        self.setWindowTitle("Calibración de flujo absoluta (estrella estándar)")
        self.resize(620, 560)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Función de sensibilidad real desde una estrella estándar (cuentas -> flujo físico), más corrección de "
            "extinción atmosférica -- equivalente a sensfunc/calibrate de IRAF. Ambas ventanas deben tener ya una "
            "calibración en longitud de onda ajustada. La referencia física se carga SIEMPRE de un archivo CALSPEC "
            "real -- nunca se inventa."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.standard_combo = QComboBox()
        self.standard_combo.addItems(list(views))
        form.addRow("Ventana de la estrella estándar (cuentas)", self.standard_combo)
        self.science_combo = QComboBox()
        self.science_combo.addItems(list(views))
        form.addRow("Ventana científica a calibrar", self.science_combo)
        self.reference_star_combo = QComboBox()
        self.reference_star_combo.addItem(_NO_REFERENCE)
        self.reference_star_combo.addItems([s.name for s in CALSPEC_STANDARD_STARS])
        form.addRow("Estrella (informativo, procedencia)", self.reference_star_combo)
        layout.addLayout(form)

        self.load_reference_button = QPushButton("Cargar espectro de referencia (CALSPEC, .fits)...")
        self.load_reference_button.clicked.connect(self._on_load_reference)
        layout.addWidget(self.load_reference_button)
        self.reference_label = QLabel("Ningún espectro de referencia cargado todavía.")
        self.reference_label.setWordWrap(True)
        layout.addWidget(self.reference_label)

        airmass_form = QFormLayout()
        self.airmass_spin = QDoubleSpinBox()
        self.airmass_spin.setRange(1.0, 10.0)
        self.airmass_spin.setDecimals(3)
        self.airmass_spin.setValue(1.0)
        airmass_form.addRow("Masa de aire (estándar)", self.airmass_spin)
        self.extinction_spin = QDoubleSpinBox()
        self.extinction_spin.setRange(0.0, 2.0)
        self.extinction_spin.setDecimals(3)
        self.extinction_spin.setValue(0.0)
        self.extinction_spin.setSuffix(" mag/masa de aire")
        airmass_form.addRow("Coeficiente de extinción", self.extinction_spin)
        self.poly_degree_spin = QSpinBox()
        self.poly_degree_spin.setRange(1, 15)
        self.poly_degree_spin.setValue(5)
        airmass_form.addRow("Grado del ajuste de sensibilidad", self.poly_degree_spin)
        self.science_airmass_spin = QDoubleSpinBox()
        self.science_airmass_spin.setRange(1.0, 10.0)
        self.science_airmass_spin.setDecimals(3)
        self.science_airmass_spin.setValue(1.0)
        airmass_form.addRow("Masa de aire (científica)", self.science_airmass_spin)
        layout.addLayout(airmass_form)

        self.standard_combo.currentTextChanged.connect(self._prefill_standard_airmass)
        self.science_combo.currentTextChanged.connect(self._prefill_science_airmass)
        self._prefill_standard_airmass(self.standard_combo.currentText())
        self._prefill_science_airmass(self.science_combo.currentText())

        self.fit_button = QPushButton("Ajustar función de sensibilidad")
        self.fit_button.clicked.connect(self._on_fit_sensitivity)
        layout.addWidget(self.fit_button)

        self.table = QTableWidget(0, 3, self)
        self.table.setHorizontalHeaderLabels(["Longitud de onda (Å)", "Sensibilidad medida", "Sensibilidad ajustada"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.save_button = QPushButton("Aplicar y guardar espectro calibrado en flujo (FITS)...")
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
            self.airmass_spin.setValue(airmass)

    def _prefill_science_airmass(self, title: str) -> None:
        view = self._views.get(title)
        airmass = _header_airmass(view) if view else None
        if airmass is not None:
            self.science_airmass_spin.setValue(airmass)

    def _on_load_reference(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar espectro de referencia CALSPEC", "", "FITS (*.fits *.fit *.fts);;Todos los archivos (*.*)"
        )
        if not path:
            return
        try:
            spectrum = load_calspec_spectrum(path)
        except (ValueError, OSError) as exc:
            self.reference_label.setText(f"No se pudo cargar «{path}»: {exc}")
            return
        self._reference_wavelength = spectrum.wavelength_angstrom
        self._reference_flux = spectrum.flux
        self._reference_path = path
        lo, hi = spectrum.wavelength_angstrom[0], spectrum.wavelength_angstrom[-1]
        self.reference_label.setText(
            f"Referencia cargada de «{path}»: {lo:.1f}-{hi:.1f} Å, unidades «{spectrum.flux_unit}» "
            f"({spectrum.wavelength_angstrom.size} punto(s) reales)."
        )

    def _on_fit_sensitivity(self) -> None:
        if self._reference_wavelength is None or self._reference_flux is None:
            self.status_label.setText("Carga primero un espectro de referencia CALSPEC real.")
            return
        standard_view = self._views.get(self.standard_combo.currentText())
        if standard_view is None or standard_view.fitted_wavelength_solution is None:
            self.status_label.setText("La ventana de la estrella estándar necesita una calibración en longitud de onda ajustada.")
            return
        exptime = _header_exptime(standard_view)
        if exptime is None:
            self.status_label.setText(
                f"{standard_view.title} no tiene EXPTIME/EXPOSURE real en la cabecera -- no se puede convertir a "
                "cuentas/s sin inventar un tiempo de exposición."
            )
            return

        wavelength, counts = _central_row_counts(standard_view)
        counts_per_s = counts / exptime
        try:
            self._sensitivity = build_sensitivity_function(
                wavelength, counts_per_s, self._reference_wavelength, self._reference_flux,
                airmass=self.airmass_spin.value(), extinction_mag_per_airmass=self.extinction_spin.value(),
                poly_degree=self.poly_degree_spin.value(),
            )
        except ValueError as exc:
            self.status_label.setText(f"No se pudo ajustar la función de sensibilidad: {exc}")
            self._sensitivity = None
            return

        fitted = self._sensitivity.evaluate(self._sensitivity.wavelength)
        self.table.setRowCount(self._sensitivity.wavelength.size)
        for row in range(self._sensitivity.wavelength.size):
            self.table.setItem(row, 0, QTableWidgetItem(f"{self._sensitivity.wavelength[row]:.2f}"))
            self.table.setItem(row, 1, QTableWidgetItem(f"{self._sensitivity.sensitivity[row]:.4g}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{fitted[row]:.4g}"))
        self.status_label.setText(
            f"Función de sensibilidad ajustada: grado {self._sensitivity.poly_degree}, "
            f"{self._sensitivity.wavelength.size} punto(s) reales usados."
        )

    def _on_save(self) -> None:
        if self._sensitivity is None:
            self.status_label.setText("Ajusta primero la función de sensibilidad.")
            return
        science_view = self._views.get(self.science_combo.currentText())
        if science_view is None or science_view.fitted_wavelength_solution is None:
            self.status_label.setText("La ventana científica necesita una calibración en longitud de onda ajustada.")
            return
        if science_view.wavelength_calibration_record is None:
            self.status_label.setText(
                f"{science_view.title} no tiene un registro de calibración en longitud de onda completo -- "
                "vuelve a calibrarla con \"Calibrar longitud de onda...\" antes de guardar."
            )
            return
        exptime = _header_exptime(science_view)
        if exptime is None:
            self.status_label.setText(
                f"{science_view.title} no tiene EXPTIME/EXPOSURE real en la cabecera -- no se puede convertir a "
                "cuentas/s sin inventar un tiempo de exposición."
            )
            return

        wavelength, counts = _central_row_counts(science_view)
        counts_per_s = counts / exptime
        calibrated_flux = calibrate_flux(
            wavelength, counts_per_s, self._sensitivity,
            airmass=self.science_airmass_spin.value(), extinction_mag_per_airmass=self.extinction_spin.value(),
        )
        self._last_calibrated_wavelength = wavelength
        self._last_calibrated_flux = calibrated_flux

        default_path = ""
        if science_view.source_path:
            from pathlib import Path

            source = Path(science_view.source_path)
            default_path = str(source.with_name(f"{source.stem}_fluxcal.fits"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar espectro calibrado en flujo", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return

        reference_name = self.reference_star_combo.currentText()
        extra_header = dict(science_view.header) if science_view.header else {}
        extra_header.update({
            "FLUXCAL": "STANDARD_STAR",
            "STDSTAR": reference_name if reference_name != _NO_REFERENCE else "",
            "STDFILE": self._reference_path or "",
            "SENSDEG": int(self._sensitivity.poly_degree),
            "AIRMASS": float(self.science_airmass_spin.value()),
            "EXTCOEF": float(self.extinction_spin.value()),
        })
        try:
            save_spectrum1d_fits(
                path, calibrated_flux, science_view.wavelength_calibration_record, header=extra_header,
                flux_bunit="erg/s/cm2/Angstrom",
            )
        except (ValueError, OSError) as exc:
            self.status_label.setText(f"No se pudo guardar «{path}»: {exc}")
            return
        self.status_label.setText(f"Espectro calibrado en flujo guardado en {path}.")

    def result_table(self) -> Table | None:
        if self._sensitivity is None:
            return None
        fitted = self._sensitivity.evaluate(self._sensitivity.wavelength)
        return Table(
            columns=("wavelength", "sensitivity_measured", "sensitivity_fitted"),
            units=("Å", "", ""),
            rows=tuple(
                (float(w), float(s), float(f))
                for w, s, f in zip(self._sensitivity.wavelength, self._sensitivity.sensitivity, fitted)
            ),
        )
