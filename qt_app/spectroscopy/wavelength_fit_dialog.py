"""Calibración en longitud de onda desde líneas de arco detectadas
automáticamente -- equivalente propio de `identify` de IRAF, sobre
`astrophysics_suite.spectroscopy.wavelength.find_arc_lines`/
`fit_wavelength_solution` sin ningún cambio. A diferencia del ajuste de
WCS (Fase 13), la localización de las líneas SÍ es automática
(`find_arc_lines` detecta picos reales sobre un fondo local robusto); lo
que el taller no puede adivinar es a qué longitud de onda conocida
corresponde cada línea detectada -- eso lo aporta el usuario, igual que
`identify` interactivo pide asociar cada línea marcada con una entrada de
un catálogo de lámpara (Hg/Ar/Ne...).

Sugerencia automática (§10): si el usuario elige una lámpara conocida y
da una dispersión/origen aproximados (de la óptica del instrumento, o
de una calibración previa), `line_catalog.match_lines_to_catalog`
propone una longitud de onda por línea detectada -- **propone, no
aplica**: el usuario sigue viendo y pudiendo corregir cada celda antes
de pulsar "Ajustar solución", la etapa de confirmación que pide el
encargo explícitamente.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.line_catalog import arc_catalog, match_lines_to_catalog
from astrophysics_suite.spectroscopy.wavelength import ArcLine, fit_wavelength_solution
from astrophysics_suite.tables.table import Table

_LAMP_OPTIONS = ("(sin especificar)", "Ne", "Ar", "He", "HeNeAr")


class WavelengthFitDialog(QDialog):
    fitted = Signal(object, object, object)
    """Emite `(WavelengthSolution, Table, WavelengthCalibrationRecord)`
    al ajustar con éxito -- el `record` lleva la lámpara declarada (si
    se dio) y `CalibrationSource.LAMP_REAL`: esta calibración siempre
    parte de líneas que el usuario ha confirmado a mano, nunca de una
    suposición aceptada en silencio."""

    def __init__(self, lines: list[ArcLine], parent=None):
        super().__init__(parent)
        self._lines = lines
        self.setWindowTitle("Calibrar longitud de onda")
        self.resize(520, 460)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Se detectaron {len(lines)} línea(s) de arco automáticamente. Introduce la "
            "longitud de onda conocida (p. ej. de un catálogo de lámpara) para cada una -- "
            "el taller no adivina a qué línea corresponde cada pico sin tu confirmación."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        degree_row = QHBoxLayout()
        degree_row.addWidget(QLabel("Grado del polinomio"))
        self.degree_spin = QSpinBox()
        self.degree_spin.setRange(1, 6)
        self.degree_spin.setValue(min(3, max(1, len(lines) - 1)))
        degree_row.addWidget(self.degree_spin)
        degree_row.addStretch(1)
        layout.addLayout(degree_row)

        suggest_grid = QGridLayout()
        suggest_grid.addWidget(QLabel("Lámpara"), 0, 0)
        self.lamp_combo = QComboBox()
        self.lamp_combo.addItems(_LAMP_OPTIONS)
        suggest_grid.addWidget(self.lamp_combo, 0, 1)
        suggest_grid.addWidget(QLabel("Dispersión aprox. (Å/px)"), 1, 0)
        self.dispersion_spin = QDoubleSpinBox()
        self.dispersion_spin.setRange(0.01, 100.0)
        self.dispersion_spin.setDecimals(3)
        self.dispersion_spin.setValue(1.4)
        suggest_grid.addWidget(self.dispersion_spin, 1, 1)
        suggest_grid.addWidget(QLabel("λ en píxel 0 aprox. (Å)"), 2, 0)
        self.zero_point_spin = QDoubleSpinBox()
        self.zero_point_spin.setRange(0.0, 20000.0)
        self.zero_point_spin.setDecimals(1)
        self.zero_point_spin.setValue(3800.0)
        suggest_grid.addWidget(self.zero_point_spin, 2, 1)
        self.suggest_button = QPushButton("Sugerir automáticamente")
        self.suggest_button.setToolTip(
            "Rellena la columna de longitud de onda con la línea de catálogo más cercana a la "
            "dispersión aproximada dada -- una SUGERENCIA que puedes corregir antes de ajustar, "
            "nunca se aplica sin que la revises."
        )
        self.suggest_button.clicked.connect(self._on_suggest)
        suggest_grid.addWidget(self.suggest_button, 0, 2, 3, 1)
        layout.addLayout(suggest_grid)

        self.table = QTableWidget(len(lines), 4, self)
        self.table.setHorizontalHeaderLabels(["Píxel", "Amplitud", "Longitud de onda", "Confianza"])
        for row, line in enumerate(lines):
            pixel_item = QTableWidgetItem(f"{line.pixel:.2f}")
            pixel_item.setFlags(pixel_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            amplitude_item = QTableWidgetItem(f"{line.amplitude:.1f}")
            amplitude_item.setFlags(amplitude_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, pixel_item)
            self.table.setItem(row, 1, amplitude_item)
            self.table.setItem(row, 2, QTableWidgetItem(""))
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, confidence_item)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.fit_button = self.button_box.addButton("Ajustar solución", QDialogButtonBox.ButtonRole.AcceptRole)
        self.fit_button.clicked.connect(self._on_fit)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_suggest(self) -> None:
        lamp_name = self.lamp_combo.currentText()
        if lamp_name == "(sin especificar)":
            self.status_label.setText("Elige una lámpara para poder sugerir correspondencias.")
            return
        catalog = arc_catalog(lamp_name)
        pixels = [line.pixel for line in self._lines]
        matches = match_lines_to_catalog(
            pixels, catalog,
            approx_dispersion_angstrom_per_px=self.dispersion_spin.value(),
            approx_wavelength_at_pixel0=self.zero_point_spin.value(),
            tolerance_angstrom=max(3.0, 3.0 * self.dispersion_spin.value()),
        )
        n_suggested = 0
        for row, match in enumerate(matches):
            if match is None:
                self.table.setItem(row, 3, QTableWidgetItem("sin coincidencia"))
                continue
            self.table.item(row, 2).setText(f"{match.catalog_line.wavelength_air_angstrom:.3f}")
            self.table.item(row, 3).setText(f"{match.confidence:.2f}")
            n_suggested += 1
        self.status_label.setText(
            f"{n_suggested} de {len(matches)} línea(s) sugerida(s) contra el catálogo de {lamp_name} -- "
            "revisa cada una antes de ajustar."
        )

    def _on_fit(self) -> None:
        wavelengths: list[float] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 2)
            text = item.text().strip() if item else ""
            if not text:
                self.status_label.setText(f"Falta la longitud de onda en la fila {row + 1}.")
                return
            try:
                wavelengths.append(float(text))
            except ValueError:
                self.status_label.setText(f"Longitud de onda no numérica en la fila {row + 1}.")
                return

        pixels = [line.pixel for line in self._lines]
        degree = self.degree_spin.value()

        # Ajuste polinómico sobre unas pocas líneas como mucho -- igual
        # que el ajuste de WCS, no hace falta hilo de fondo.
        try:
            solution = fit_wavelength_solution(pixels, wavelengths, degree=degree)
        except ValueError as exc:
            self.status_label.setText(f"Error: {exc}")
            return

        self.status_label.setText(f"Solución ajustada: RMS={solution.rms_residual:.4f} con {len(pixels)} línea(s).")
        table = Table(
            columns=("line", "pixel", "wavelength", "residual"),
            units=("", "px", "", ""),
            rows=tuple((i + 1, p, w, float(r)) for i, (p, w, r) in enumerate(zip(pixels, wavelengths, solution.residuals))),
        )
        lamp_name = self.lamp_combo.currentText()
        record = WavelengthCalibrationRecord(
            solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=len(pixels),
            lamp_name=None if lamp_name == "(sin especificar)" else lamp_name,
        )
        self.fitted.emit(solution, table, record)
        self.accept()
