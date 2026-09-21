"""Velocidad radial multi-línea + corrección heliocéntrica/baricéntrica
-- diálogo dedicado (menú Espectroscopía) sobre `astrophysics_suite.
spectroscopy.radial_velocity`/`heliocentric`.

Nunca depende de una sola línea (§59): mide independientemente cada
línea de un conjunto elegido por el usuario y combina las medidas reales
mostrando su dispersión explícita -- nunca oculta esa dispersión detrás
de un único número. La corrección heliocéntrica/baricéntrica (§60) es
un paso EXPLÍCITO y separado, nunca aplicado en silencio a la velocidad
medida: requiere que el usuario dé coordenadas reales del objeto, del
observatorio y el instante de observación -- sin ellos, no hay
corrección que aplicar.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QGroupBox,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.heliocentric import apply_barycentric_correction, compute_barycentric_correction
from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES, CALCIUM_LINES, NEBULAR_EMISSION_LINES, SODIUM_LINES
from astrophysics_suite.spectroscopy.radial_velocity import MultiLineRVResult, measure_multi_line_radial_velocity
from astrophysics_suite.tables.table import Table

_LINE_SETS: dict[str, tuple] = {
    "Balmer (H, estelar)": BALMER_LINES,
    "Ca II H&K (estelar)": CALCIUM_LINES,
    "Na D (estelar/interestelar)": SODIUM_LINES,
    "Nebulares ([O III]/[N II]/[S II])": NEBULAR_EMISSION_LINES,
}


def _central_row_spectrum(view) -> tuple[np.ndarray, np.ndarray]:
    """Misma convención que `combine_spectra_dialog`/`wavelength_fit_
    dialog`: la fila central de la imagen como espectro 1D, en longitud
    de onda si la ventana ya tiene una calibración ajustada."""
    row_index = view.data.shape[0] // 2
    flux = view.data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    wavelength = view.fitted_wavelength_solution.pixel_to_wavelength(pixel)
    return np.asarray(wavelength, dtype=np.float64), flux


class RadialVelocityDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self._wavelength, self._flux = _central_row_spectrum(view)
        self._last_result: MultiLineRVResult | None = None
        self._last_correction = None
        self.setWindowTitle("Medir velocidad radial")
        self.resize(560, 620)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Mide la velocidad radial de forma independiente en cada línea del conjunto elegido "
            "(nunca depende de una sola línea) y combina las medidas reales mostrando su dispersión "
            "entre líneas -- una dispersión grande avisa de una identificación o calibración dudosa."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.line_set_combo = QComboBox()
        self.line_set_combo.addItems(list(_LINE_SETS))
        form.addRow("Conjunto de líneas", self.line_set_combo)
        self.continuum_degree_spin = QSpinBox()
        self.continuum_degree_spin.setRange(0, 6)
        self.continuum_degree_spin.setValue(2)
        form.addRow("Grado del continuo", self.continuum_degree_spin)
        self.continuum_reject_combo = QComboBox()
        self.continuum_reject_combo.addItems(["both", "absorption", "emission"])
        form.addRow("Rechazo del continuo", self.continuum_reject_combo)
        self.window_halfwidth_spin = QDoubleSpinBox()
        self.window_halfwidth_spin.setRange(0.1, 200.0)
        self.window_halfwidth_spin.setDecimals(2)
        self.window_halfwidth_spin.setValue(8.0)
        self.window_halfwidth_spin.setSuffix(" Å")
        form.addRow("Semiancho de ventana por línea", self.window_halfwidth_spin)
        self.relativistic_check = QCheckBox("Fórmula relativista (en vez de clásica)")
        form.addRow(self.relativistic_check)
        layout.addLayout(form)

        self.measure_button = QPushButton("Medir velocidad radial")
        self.measure_button.clicked.connect(self._on_measure)
        layout.addWidget(self.measure_button)

        self.table = QTableWidget(0, 5, self)
        self.table.setHorizontalHeaderLabels(
            ["Línea", "λ reposo aire (Å)", "λ reposo vacío (Å)", "λ medida (Å)", "Velocidad (km/s)"]
        )
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.summary_label = QLabel("")
        self.summary_label.setWordWrap(True)
        layout.addWidget(self.summary_label)

        helio_group = QGroupBox("Corrección heliocéntrica/baricéntrica (§60 -- paso separado y explícito)")
        helio_form = QFormLayout(helio_group)
        self.ra_spin = QDoubleSpinBox()
        self.ra_spin.setRange(0.0, 360.0)
        self.ra_spin.setDecimals(5)
        helio_form.addRow("RA del objeto (°, J2000)", self.ra_spin)
        self.dec_spin = QDoubleSpinBox()
        self.dec_spin.setRange(-90.0, 90.0)
        self.dec_spin.setDecimals(5)
        helio_form.addRow("Dec del objeto (°, J2000)", self.dec_spin)
        self.obstime_combo = QComboBox()
        self.obstime_combo.setEditable(True)
        header_date = ""
        if view.header:
            header_date = str(view.header.get("DATE-OBS", "") or "")
        if header_date:
            self.obstime_combo.addItem(header_date)
        helio_form.addRow("Instante de observación (UTC, ISO)", self.obstime_combo)
        self.obs_lon_spin = QDoubleSpinBox()
        self.obs_lon_spin.setRange(-180.0, 180.0)
        self.obs_lon_spin.setDecimals(5)
        helio_form.addRow("Longitud del observatorio (°, E+)", self.obs_lon_spin)
        self.obs_lat_spin = QDoubleSpinBox()
        self.obs_lat_spin.setRange(-90.0, 90.0)
        self.obs_lat_spin.setDecimals(5)
        helio_form.addRow("Latitud del observatorio (°)", self.obs_lat_spin)
        self.obs_height_spin = QDoubleSpinBox()
        self.obs_height_spin.setRange(-500.0, 9000.0)
        self.obs_height_spin.setDecimals(1)
        self.obs_height_spin.setSuffix(" m")
        helio_form.addRow("Altitud del observatorio", self.obs_height_spin)
        self.helio_kind_combo = QComboBox()
        self.helio_kind_combo.addItems(["barycentric", "heliocentric"])
        helio_form.addRow("Marco de referencia", self.helio_kind_combo)
        self.compute_correction_button = QPushButton("Calcular y aplicar corrección")
        self.compute_correction_button.clicked.connect(self._on_compute_correction)
        helio_form.addRow(self.compute_correction_button)
        self.correction_label = QLabel("")
        self.correction_label.setWordWrap(True)
        helio_form.addRow(self.correction_label)
        layout.addWidget(helio_group)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    def _on_measure(self) -> None:
        continuum_fit = fit_continuum(
            self._wavelength, self._flux, degree=self.continuum_degree_spin.value(),
            reject=self.continuum_reject_combo.currentText(),
        )
        lines = _LINE_SETS[self.line_set_combo.currentText()]
        result = measure_multi_line_radial_velocity(
            self._wavelength, self._flux, continuum_fit.continuum, lines,
            window_halfwidth=self.window_halfwidth_spin.value(), relativistic=self.relativistic_check.isChecked(),
        )
        self._last_result = result

        self.table.setRowCount(len(result.measurements))
        for row, m in enumerate(result.measurements):
            self.table.setItem(row, 0, QTableWidgetItem(m.line.label))
            self.table.setItem(row, 1, QTableWidgetItem(f"{m.line.wavelength_air_angstrom:.3f}"))
            self.table.setItem(row, 2, QTableWidgetItem(f"{m.line.wavelength_vacuum_angstrom:.3f}"))
            self.table.setItem(row, 3, QTableWidgetItem(f"{m.measurement.center_wavelength:.3f}"))
            self.table.setItem(row, 4, QTableWidgetItem(f"{m.velocity_km_s:.2f}"))

        if result.n_lines_used == 0:
            self.summary_label.setText(
                f"Ninguna de las {result.n_lines_requested} línea(s) del conjunto elegido se pudo medir "
                "en este espectro (fuera de rango, o sin señal detectable)."
            )
            return
        dispersion_text = f"{result.velocity_dispersion_km_s:.2f} km/s" if result.velocity_dispersion_km_s is not None else "n/d (una sola línea)"
        self.summary_label.setText(
            f"{result.n_lines_used}/{result.n_lines_requested} línea(s) medida(s). "
            f"Velocidad combinada = {result.combined_velocity_km_s:.2f} km/s "
            f"(± {result.combined_velocity_uncertainty_km_s:.2f} km/s si hay >1 línea). "
            f"Dispersión entre líneas: {dispersion_text} -- observada, no una lámpara."
        )

    def _on_compute_correction(self) -> None:
        obstime_text = self.obstime_combo.currentText().strip()
        if not obstime_text:
            self.correction_label.setText("Introduce el instante de observación (DATE-OBS, UTC) -- no se asume ninguno.")
            return
        try:
            correction = compute_barycentric_correction(
                ra_deg=self.ra_spin.value(), dec_deg=self.dec_spin.value(), obstime_iso=obstime_text,
                observatory_longitude_deg=self.obs_lon_spin.value(), observatory_latitude_deg=self.obs_lat_spin.value(),
                observatory_height_m=self.obs_height_spin.value(), kind=self.helio_kind_combo.currentText(),
            )
        except ValueError as exc:
            self.correction_label.setText(f"No se pudo calcular la corrección: {exc}")
            return
        self._last_correction = correction
        text = correction.describe()
        if self._last_result is not None and self._last_result.combined_velocity_km_s is not None:
            corrected = apply_barycentric_correction(self._last_result.combined_velocity_km_s, correction)
            text += (
                f"\nVelocidad observada combinada {self._last_result.combined_velocity_km_s:.2f} km/s + "
                f"corrección = {corrected:.2f} km/s ({correction.kind})."
            )
        self.correction_label.setText(text)

    def result_table(self) -> Table | None:
        """`Table` exportable a CSV (mismo mecanismo que el resto de
        diálogos) con la última medición -- `None` si aún no se ha
        medido nada."""
        if self._last_result is None or not self._last_result.measurements:
            return None
        return Table(
            columns=("line", "rest_wavelength_air", "rest_wavelength_vacuum", "measured_wavelength", "velocity"),
            units=("", "Å", "Å", "Å", "km/s"),
            rows=tuple(
                (
                    m.line.label, m.line.wavelength_air_angstrom, m.line.wavelength_vacuum_angstrom,
                    m.measurement.center_wavelength, m.velocity_km_s,
                )
                for m in self._last_result.measurements
            ),
        )
