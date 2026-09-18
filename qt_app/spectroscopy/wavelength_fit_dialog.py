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
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.wavelength import ArcLine, fit_wavelength_solution
from astrophysics_suite.tables.table import Table


class WavelengthFitDialog(QDialog):
    fitted = Signal(object, object)
    """Emite `(WavelengthSolution, Table)` al ajustar con éxito."""

    def __init__(self, lines: list[ArcLine], parent=None):
        super().__init__(parent)
        self._lines = lines
        self.setWindowTitle("Calibrar longitud de onda")
        self.resize(480, 380)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Se detectaron {len(lines)} línea(s) de arco automáticamente. Introduce la "
            "longitud de onda conocida (p. ej. de un catálogo de lámpara) para cada una -- "
            "el taller no adivina a qué línea corresponde cada pico."
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

        self.table = QTableWidget(len(lines), 3, self)
        self.table.setHorizontalHeaderLabels(["Píxel", "Amplitud", "Longitud de onda"])
        for row, line in enumerate(lines):
            pixel_item = QTableWidgetItem(f"{line.pixel:.2f}")
            pixel_item.setFlags(pixel_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            amplitude_item = QTableWidgetItem(f"{line.amplitude:.1f}")
            amplitude_item.setFlags(amplitude_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, pixel_item)
            self.table.setItem(row, 1, amplitude_item)
            self.table.setItem(row, 2, QTableWidgetItem(""))
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
        self.fitted.emit(solution, table)
        self.accept()
