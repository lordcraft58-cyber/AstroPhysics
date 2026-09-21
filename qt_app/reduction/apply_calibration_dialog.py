"""Aplica bias/dark/flat maestros (elegidos por nombre de la biblioteca
de la sesión) a la imagen activa -- equivalente propio de `ccdproc` de
IRAF, sobre `astrophysics_suite.reduction.calibration.calibrate_frame`
sin ningún cambio.
"""
from __future__ import annotations

from dataclasses import dataclass

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

from astrophysics_suite.imtools.arithmetic import UncertainImage
from astrophysics_suite.reduction.calibration import calibrate_frame
from astrophysics_suite.reduction.provenance import ReductionRecord
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.workers import CallableWorker

NONE_OPTION = "(ninguno)"


@dataclass(frozen=True)
class CalibrationOutcome:
    image: UncertainImage
    """Resultado calibrado, incertidumbre incluida (antes se descartaba:
    solo `.data` llegaba al llamador)."""
    summary: str
    record: ReductionRecord
    """Qué se le hizo de verdad -- mismo tipo que ya usa la reducción por
    sesión, para poder escribir cabecera/procedencia con las mismas
    `reduction_header_cards`/`build_reduction_provenance`."""
    master_input_hashes: tuple[tuple[str, str], ...]
    """sha256 reales de los maestros usados, solo de los que ya estaban
    guardados a disco (`NamedMasterFrame.path`) -- uno recién combinado en
    esta sesión y nunca guardado no tiene archivo que hashear, y no se
    inventa uno. El hash de la propia imagen científica lo añade el
    llamador (`main_window`), que es quien conoce su `source_path`."""


class ApplyCalibrationDialog(QDialog):
    calibrated = Signal(object)
    """Emite un `CalibrationOutcome` real, no solo el array de datos --
    lo necesita el llamador para poder ofrecer guardar el resultado con
    procedencia real (ver `main_window._offer_to_save_calibrated_fits`)."""

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
        # Procedencia real (mismo criterio que `ReduceSessionDialog._on_run`):
        # solo hay un sha256 real que dar si el maestro ya se guardó a disco.
        master_bias_path = self.library.entry(bias_name).path if bias_name != NONE_OPTION else None
        master_dark_path = self.library.entry(dark_name).path if dark_name != NONE_OPTION else None
        master_flat_path = self.library.entry(flat_name).path if flat_name != NONE_OPTION else None
        science_exposure_s = self.exposure_spin.value() if master_dark is not None else None
        gain = self.gain_spin.value()
        read_noise = self.read_noise_spin.value()
        raw = self.raw_data

        def run() -> CalibrationOutcome:
            from astrophysics_suite.io.fits_reader import sha256_file

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
            summary = ", ".join(parts) or "sin pasos aplicados"

            master_hashes: list[tuple[str, str]] = []
            if master_bias is not None and master_bias_path:
                master_hashes.append(("master_bias", sha256_file(master_bias_path)))
            if master_dark is not None and master_dark_path:
                master_hashes.append(("master_dark", sha256_file(master_dark_path)))
            if master_flat is not None and master_flat_path:
                master_hashes.append(("master_flat", sha256_file(master_flat_path)))

            record = ReductionRecord(steps=steps, gain_e_per_adu=gain, read_noise_e=read_noise)
            return CalibrationOutcome(image=image, summary=summary, record=record, master_input_hashes=tuple(master_hashes))

        self.apply_button.setEnabled(False)
        self.status_label.setText("Calibrando...")
        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, outcome: CalibrationOutcome) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText("")
        self.calibrated.emit(outcome)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
