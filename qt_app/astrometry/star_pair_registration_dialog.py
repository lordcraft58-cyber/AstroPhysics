"""Registro entre imágenes por pares de estrellas emparejadas a clic --
equivalente propio de `geomap` interactivo de IRAF cuando ninguna de las
dos imágenes tiene WCS (a diferencia de "Registrar por WCS compartido...",
que exige que ambas lo tengan). Este diálogo solo reúne la configuración
(qué ventana es referencia, cuál se va a transformar, qué modelo, cuántos
pares); la selección de posiciones a clic en dos ventanas MDI distintas y
en el mismo orden no encaja en un formulario, así que la orquesta
`MainWindow` directamente (mismo patrón que "Ajustar WCS...")."""
from __future__ import annotations

from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QSpinBox, QVBoxLayout


class StarPairConfigDialog(QDialog):
    def __init__(self, titles: list[str], active_title: str, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Registrar por pares de estrellas")
        self.resize(440, 200)

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.reference_combo = QComboBox()
        self.reference_combo.addItems(titles)
        if active_title in titles:
            self.reference_combo.setCurrentText(active_title)
        form.addRow("Imagen de referencia", self.reference_combo)

        self.target_combo = QComboBox()
        self.target_combo.addItems(titles)
        if len(titles) > 1:
            self.target_combo.setCurrentIndex(1 if titles[0] == active_title else 0)
        form.addRow("Imagen a transformar", self.target_combo)

        self.model_combo = QComboBox()
        self.model_combo.addItems(["affine", "similarity"])
        form.addRow("Modelo de transformación", self.model_combo)

        self.n_pairs_spin = QSpinBox()
        self.n_pairs_spin.setRange(3, 50)
        self.n_pairs_spin.setValue(3)
        form.addRow("Número de pares a marcar", self.n_pairs_spin)

        layout.addLayout(form)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.mark_button = self.button_box.addButton("Marcar pares...", QDialogButtonBox.ButtonRole.AcceptRole)
        self.mark_button.clicked.connect(self.accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def reference_title(self) -> str:
        return self.reference_combo.currentText()

    def target_title(self) -> str:
        return self.target_combo.currentText()

    def model(self) -> str:
        return self.model_combo.currentText()

    def n_pairs(self) -> int:
        return self.n_pairs_spin.value()
