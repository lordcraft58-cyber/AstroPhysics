"""Aritmética entre dos imágenes -- equivalente propio de `imarith` de
IRAF, sobre `astrophysics_suite.imtools.arithmetic.UncertainImage` sin
ningún cambio (incluida su propagación de incertidumbre, algo que el
`imarith` original nunca hacía). Necesita elegir una segunda ventana MDI,
algo que no encaja en "un proceso transforma la imagen activa"
(`ProcessDefinition.run`) -- por eso vive en un diálogo dedicado, mismo
patrón que "Aplicar calibración..." en el menú Reducción.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from astrophysics_suite.imtools.arithmetic import UncertainImage
from qt_app.workers import CallableWorker

_OPERATIONS = {"Sumar (+)": "+", "Restar (-)": "-", "Multiplicar (x)": "x", "Dividir (/)": "/"}


class ArithmeticDialog(QDialog):
    computed = Signal(object, str)
    """(datos resultantes, título sugerido para la nueva ventana)."""

    def __init__(self, windows: dict[str, np.ndarray], active_title: str, parent=None):
        """`windows`: título de ventana -> array de datos, de todas las
        ventanas de imagen MDI abiertas actualmente (incluida la activa).
        La incertidumbre de cada operando se trata como no estimada
        (cero explícito, no un modelo de ruido inventado): esta es una
        utilidad genérica entre dos imágenes cualesquiera, no una
        calibración con un modelo de ganancia/ruido de lectura conocido.
        """
        super().__init__(parent)
        self._windows = windows
        self.setWindowTitle("Aritmética entre imágenes")
        self.resize(420, 220)
        self._worker: CallableWorker | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        titles = list(windows.keys())
        self.first_combo = QComboBox()
        self.first_combo.addItems(titles)
        if active_title in windows:
            self.first_combo.setCurrentText(active_title)
        form.addRow("Primera imagen", self.first_combo)

        self.operation_combo = QComboBox()
        self.operation_combo.addItems(list(_OPERATIONS.keys()))
        form.addRow("Operación", self.operation_combo)

        self.second_combo = QComboBox()
        self.second_combo.addItems(titles)
        if len(titles) > 1:
            self.second_combo.setCurrentIndex(1 if titles[0] == active_title else 0)
        form.addRow("Segunda imagen", self.second_combo)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.button_box.addButton("Aplicar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.clicked.connect(self._on_apply)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_apply(self) -> None:
        first_title = self.first_combo.currentText()
        second_title = self.second_combo.currentText()
        if first_title == second_title:
            self.status_label.setText("Elige dos ventanas distintas.")
            return

        first_data = self._windows[first_title]
        second_data = self._windows[second_title]
        if first_data.shape != second_data.shape:
            self.status_label.setText(f"Las imágenes no tienen la misma forma: {first_data.shape} vs {second_data.shape}.")
            return

        symbol = _OPERATIONS[self.operation_combo.currentText()]
        title = f"{first_title} {symbol} {second_title}"

        def run() -> tuple[np.ndarray, str]:
            first_image = UncertainImage(data=first_data.astype(np.float64), uncertainty=np.zeros_like(first_data, dtype=np.float64))
            second_image = UncertainImage(data=second_data.astype(np.float64), uncertainty=np.zeros_like(second_data, dtype=np.float64))
            if symbol == "+":
                result = first_image + second_image
            elif symbol == "-":
                result = first_image - second_image
            elif symbol == "x":
                result = first_image * second_image
            else:
                result = first_image / second_image
            return result.data, title

        self.apply_button.setEnabled(False)
        self.status_label.setText("Calculando...")
        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, result: tuple[np.ndarray, str]) -> None:
        data, title = result
        self.apply_button.setEnabled(True)
        self.status_label.setText("")
        self.computed.emit(data, title)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
