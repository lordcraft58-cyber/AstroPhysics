"""Aplica bias/dark/flat maestros (elegidos por nombre de la biblioteca
de la sesión) a la imagen activa -- equivalente propio de `ccdproc` de
IRAF, sobre `astrophysics_suite.reduction.calibration.calibrate_frame`
sin ningún cambio.
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from astrophysics_suite.reduction.calibration import calibrate_frame
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.workers import CallableWorker

NONE_OPTION = "(ninguno)"


class ApplyCalibrationDialog(QDialog):
    calibrated = Signal(object, str)
    """(datos calibrados, resumen de pasos aplicados)."""

    def __init__(self, library: MasterFrameLibrary, raw_data, parent=None):
        super().__init__(parent)
        self.library = library
        self.raw_data = raw_data
        self.setWindowTitle("Aplicar calibración")
        self.resize(420, 320)
        self._worker: CallableWorker | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        self.bias_combo = QComboBox()
        self.bias_combo.addItem(NONE_OPTION)
        self.bias_combo.addItems(library.names_for_kind("bias"))
        form.addRow("Bias maestro", self.bias_combo)

        self.dark_combo = QComboBox()
        self.dark_combo.addItem(NONE_OPTION)
        self.dark_combo.addItems(library.names_for_kind("dark"))
        self.dark_combo.currentTextChanged.connect(self._update_exposure_visibility)
        form.addRow("Dark maestro", self.dark_combo)

        self.flat_combo = QComboBox()
        self.flat_combo.addItem(NONE_OPTION)
        self.flat_combo.addItems(library.names_for_kind("flat"))
        form.addRow("Flat maestro", self.flat_combo)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.001, 36000.0)
        self.exposure_spin.setValue(60.0)
        self.exposure_spin.setSuffix(" s")
        self.exposure_label = QLabel("Exposición de la imagen científica")
        form.addRow(self.exposure_label, self.exposure_spin)

        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.01, 100.0)
        self.gain_spin.setValue(1.0)
        self.gain_spin.setSuffix(" e-/ADU")
        form.addRow("Ganancia", self.gain_spin)

        self.read_noise_spin = QDoubleSpinBox()
        self.read_noise_spin.setRange(0.0, 200.0)
        self.read_noise_spin.setValue(5.0)
        self.read_noise_spin.setSuffix(" e-")
        form.addRow("Ruido de lectura", self.read_noise_spin)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.button_box.addButton("Aplicar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.clicked.connect(self._on_apply)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._update_exposure_visibility(self.dark_combo.currentText())

    def _update_exposure_visibility(self, dark_name: str) -> None:
        needs_exposure = dark_name != NONE_OPTION
        self.exposure_label.setVisible(needs_exposure)
        self.exposure_spin.setVisible(needs_exposure)

    def _on_apply(self) -> None:
        bias_name = self.bias_combo.currentText()
        dark_name = self.dark_combo.currentText()
        flat_name = self.flat_combo.currentText()
        if bias_name == dark_name == flat_name == NONE_OPTION:
            self.status_label.setText("Selecciona al menos un fotograma maestro.")
            return

        master_bias = self.library.get(bias_name) if bias_name != NONE_OPTION else None
        master_dark = self.library.get(dark_name) if dark_name != NONE_OPTION else None
        master_flat = self.library.get(flat_name) if flat_name != NONE_OPTION else None
        science_exposure_s = self.exposure_spin.value() if master_dark is not None else None
        gain = self.gain_spin.value()
        read_noise = self.read_noise_spin.value()
        raw = self.raw_data

        def run():
            image, steps = calibrate_frame(
                raw,
                gain_e_per_adu=gain,
                read_noise_e=read_noise,
                science_exposure_s=science_exposure_s,
                master_bias=master_bias,
                master_dark=master_dark,
                master_flat=master_flat,
            )
            parts = []
            if steps.bias_subtracted:
                parts.append("bias restado")
            if steps.dark_subtracted:
                parts.append(f"dark restado (x{steps.dark_scale_factor:.3f})")
            if steps.flat_divided:
                parts.append("flat dividido")
            return image.data, ", ".join(parts) or "sin pasos aplicados"

        self.apply_button.setEnabled(False)
        self.status_label.setText("Calibrando...")
        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, result) -> None:
        data, summary = result
        self.apply_button.setEnabled(True)
        self.status_label.setText("")
        self.calibrated.emit(data, summary)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
