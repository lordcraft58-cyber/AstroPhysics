"""Reduce una sesión real de LIGHTS -- el hueco principal que señalaba el
Mapa de capacidades IRAF (`docs/audit/13-IRAF-CAPABILITY-MAP.md`, bloque
`ccdred`): hasta ahora la GUI solo podía calibrar una imagen activa a la
vez ("Aplicar calibración..."). Este diálogo aplica
`astrophysics_suite.reduction.session_pipeline.reduce_light_frames` a
tantos archivos LIGHT como el usuario seleccione, con overscan/recorte,
máscara de píxeles defectuosos y franjas opcionales, y escribe cada
producto calibrado (más un combinado opcional con rechazo de outliers) a
una carpeta de salida -- sin abrir N ventanas MDI de golpe, que sería
impracticable para una sesión real de decenas de exposiciones.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from astrophysics_suite.reduction.bad_pixel_mask import build_bad_pixel_mask
from astrophysics_suite.reduction.session_pipeline import reduce_light_frames
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.workers import CallableWorker

NONE_OPTION = "(ninguno)"
MAX_REGION = 100000


@dataclass(frozen=True)
class SessionReductionOutcome:
    output_paths: tuple[str, ...]
    combined_path: str | None
    combined_data: object | None
    n_frames: int


class ReduceSessionDialog(QDialog):
    session_reduced = Signal(object)
    """Emite `SessionReductionOutcome` al terminar con éxito."""

    def __init__(self, library: MasterFrameLibrary, parent=None):
        super().__init__(parent)
        self.library = library
        self.setWindowTitle("Reducir sesión de LIGHTS")
        self.resize(560, 700)
        self._worker: CallableWorker | None = None
        self._fringe_path: str | None = None
        self._output_dir: str | None = None

        layout = QVBoxLayout(self)

        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("LIGHTS de la sesión"))
        files_header.addStretch(1)
        add_button = QPushButton("+ Añadir...")
        add_button.clicked.connect(self._add_files)
        files_header.addWidget(add_button)
        layout.addLayout(files_header)
        self.file_list = QListWidget()
        self.file_list.setMaximumHeight(110)
        layout.addWidget(self.file_list)

        masters_group = QGroupBox("Fotogramas maestros (de la biblioteca de la sesión)")
        masters_form = QFormLayout(masters_group)
        self.bias_combo = QComboBox()
        self.bias_combo.addItem(NONE_OPTION)
        self.bias_combo.addItems(library.names_for_kind("bias"))
        masters_form.addRow("Bias maestro", self.bias_combo)
        self.dark_combo = QComboBox()
        self.dark_combo.addItem(NONE_OPTION)
        self.dark_combo.addItems(library.names_for_kind("dark"))
        masters_form.addRow("Dark maestro", self.dark_combo)
        self.flat_combo = QComboBox()
        self.flat_combo.addItem(NONE_OPTION)
        self.flat_combo.addItems(library.names_for_kind("flat"))
        self.flat_combo.currentTextChanged.connect(self._update_bad_pixel_visibility)
        masters_form.addRow("Flat maestro", self.flat_combo)
        layout.addWidget(masters_group)

        self.bad_pixel_check = QCheckBox("Detectar y corregir píxeles defectuosos automáticamente desde el flat")
        layout.addWidget(self.bad_pixel_check)
        self._update_bad_pixel_visibility(self.flat_combo.currentText())

        fringe_row = QHBoxLayout()
        fringe_row.addWidget(QLabel("Patrón de franjas maestro (opcional)"))
        self.fringe_label = QLabel(NONE_OPTION)
        self.fringe_label.setObjectName("Muted")
        fringe_row.addWidget(self.fringe_label, 1)
        fringe_button = QPushButton("Examinar...")
        fringe_button.clicked.connect(self._pick_fringe_file)
        fringe_row.addWidget(fringe_button)
        layout.addLayout(fringe_row)

        overscan_group = QGroupBox("Overscan y recorte")
        overscan_group.setCheckable(True)
        overscan_group.setChecked(False)
        self.overscan_group = overscan_group
        overscan_layout = QFormLayout(overscan_group)
        self.overscan_row_start, self.overscan_row_end = self._region_spins()
        overscan_layout.addRow("Overscan filas [inicio, fin)", self._region_row(self.overscan_row_start, self.overscan_row_end))
        self.overscan_col_start, self.overscan_col_end = self._region_spins()
        overscan_layout.addRow("Overscan columnas [inicio, fin)", self._region_row(self.overscan_col_start, self.overscan_col_end))
        self.trim_check = QCheckBox("Recortar tras sustraer overscan")
        overscan_layout.addRow(self.trim_check)
        self.trim_row_start, self.trim_row_end = self._region_spins()
        overscan_layout.addRow("Recorte filas [inicio, fin)", self._region_row(self.trim_row_start, self.trim_row_end))
        self.trim_col_start, self.trim_col_end = self._region_spins()
        overscan_layout.addRow("Recorte columnas [inicio, fin)", self._region_row(self.trim_col_start, self.trim_col_end))
        layout.addWidget(overscan_group)

        noise_form = QFormLayout()
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(0.01, 100.0)
        self.gain_spin.setValue(1.0)
        self.gain_spin.setSuffix(" e-/ADU")
        noise_form.addRow("Ganancia", self.gain_spin)
        self.read_noise_spin = QDoubleSpinBox()
        self.read_noise_spin.setRange(0.0, 200.0)
        self.read_noise_spin.setValue(5.0)
        self.read_noise_spin.setSuffix(" e-")
        noise_form.addRow("Ruido de lectura", self.read_noise_spin)
        layout.addLayout(noise_form)

        combine_group = QGroupBox("Combinación final")
        combine_group.setCheckable(True)
        combine_group.setChecked(True)
        self.combine_group = combine_group
        combine_form = QFormLayout(combine_group)
        self.combine_method_combo = QComboBox()
        self.combine_method_combo.addItems(["median", "mean"])
        combine_form.addRow("Método", self.combine_method_combo)
        self.sigma_clip_spin = QDoubleSpinBox()
        self.sigma_clip_spin.setRange(1.0, 20.0)
        self.sigma_clip_spin.setValue(3.0)
        self.sigma_clip_spin.setSuffix(" sigma")
        combine_form.addRow("Rechazo de outliers", self.sigma_clip_spin)
        layout.addWidget(combine_group)

        output_row = QHBoxLayout()
        output_row.addWidget(QLabel("Carpeta de salida"))
        self.output_label = QLabel(NONE_OPTION)
        self.output_label.setObjectName("Muted")
        output_row.addWidget(self.output_label, 1)
        output_button = QPushButton("Examinar...")
        output_button.clicked.connect(self._pick_output_dir)
        output_row.addWidget(output_button)
        layout.addLayout(output_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.run_button = QPushButton("Reducir sesión")
        self.run_button.setObjectName("Accent")
        self.run_button.clicked.connect(self._on_run)
        self.button_box.addButton(self.run_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    @staticmethod
    def _region_spins() -> tuple[QSpinBox, QSpinBox]:
        start = QSpinBox()
        start.setRange(0, MAX_REGION)
        end = QSpinBox()
        end.setRange(0, MAX_REGION)
        return start, end

    @staticmethod
    def _region_row(start: QSpinBox, end: QSpinBox) -> QHBoxLayout:
        row = QHBoxLayout()
        row.addWidget(start)
        row.addWidget(QLabel("a"))
        row.addWidget(end)
        return row

    def _update_bad_pixel_visibility(self, flat_name: str) -> None:
        self.bad_pixel_check.setEnabled(flat_name != NONE_OPTION)
        if flat_name == NONE_OPTION:
            self.bad_pixel_check.setChecked(False)

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar LIGHTS", "", "FITS (*.fits *.fit *.fts);;Todos los archivos (*.*)")
        for path in paths:
            self.file_list.addItem(Path(path).name)
            self.file_list.item(self.file_list.count() - 1).setData(Qt.ItemDataRole.UserRole, path)

    def _selected_paths(self) -> list[str]:
        return [self.file_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list.count())]

    def _pick_fringe_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Patrón de franjas maestro", "", "FITS (*.fits *.fit *.fts);;Todos los archivos (*.*)")
        if path:
            self._fringe_path = path
            self.fringe_label.setText(Path(path).name)

    def _pick_output_dir(self) -> None:
        directory = QFileDialog.getExistingDirectory(self, "Carpeta de salida")
        if directory:
            self._output_dir = directory
            self.output_label.setText(directory)

    @staticmethod
    def _slice_or_none(start: QSpinBox, end: QSpinBox) -> slice:
        end_value = end.value()
        return slice(start.value(), end_value if end_value > 0 else None)

    def _on_run(self) -> None:
        light_paths = self._selected_paths()
        if not light_paths:
            self.status_label.setText("Añade al menos un LIGHT.")
            return
        if not self._output_dir:
            self.status_label.setText("Elige una carpeta de salida.")
            return

        bias_name = self.bias_combo.currentText()
        dark_name = self.dark_combo.currentText()
        flat_name = self.flat_combo.currentText()
        master_bias = self.library.get(bias_name) if bias_name != NONE_OPTION else None
        master_dark = self.library.get(dark_name) if dark_name != NONE_OPTION else None
        master_flat = self.library.get(flat_name) if flat_name != NONE_OPTION else None

        overscan_region = None
        trim_region = None
        if self.overscan_group.isChecked():
            overscan_region = (
                self._slice_or_none(self.overscan_row_start, self.overscan_row_end),
                self._slice_or_none(self.overscan_col_start, self.overscan_col_end),
            )
            if self.trim_check.isChecked():
                trim_region = (
                    self._slice_or_none(self.trim_row_start, self.trim_row_end),
                    self._slice_or_none(self.trim_col_start, self.trim_col_end),
                )

        build_bad_pixels = self.bad_pixel_check.isChecked() and master_flat is not None
        fringe_path = self._fringe_path
        gain = self.gain_spin.value()
        read_noise = self.read_noise_spin.value()
        combine = self.combine_group.isChecked()
        combine_method = self.combine_method_combo.currentText()
        sigma_clip = self.sigma_clip_spin.value()
        output_dir = self._output_dir

        def run() -> SessionReductionOutcome:
            from astrophysics_suite.io.fits_loader import load_image
            from astrophysics_suite.io.fits_writer import save_fits_image

            loaded = [load_image(p, band="", role="science") for p in light_paths]
            light_frames = [li.legacy_image.data for li in loaded]
            headers = [li.legacy_image.header for li in loaded]

            science_exposures_s = None
            if master_dark is not None:
                exposures = [li.legacy_image.exptime for li in loaded]
                missing = [light_paths[i] for i, exp in enumerate(exposures) if exp is None]
                if missing:
                    raise ValueError(
                        "No se encontró EXPTIME en la cabecera de: " + ", ".join(Path(p).name for p in missing)
                    )
                science_exposures_s = exposures

            master_fringe_data = load_image(fringe_path, band="", role="calibration").legacy_image.data if fringe_path else None
            bad_pixel_mask = build_bad_pixel_mask(master_flat.data) if build_bad_pixels else None

            result = reduce_light_frames(
                light_frames,
                light_paths=light_paths,
                overscan_region=overscan_region,
                trim_region=trim_region,
                gain_e_per_adu=gain,
                read_noise_e=read_noise,
                science_exposures_s=science_exposures_s,
                master_bias=master_bias,
                master_dark=master_dark,
                master_flat=master_flat,
                bad_pixel_mask=bad_pixel_mask,
                master_fringe=master_fringe_data,
                combine=combine,
                combine_method=combine_method,
                combine_sigma_clip=sigma_clip,
            )

            output_paths = []
            for index, frame in enumerate(result.frames):
                out_path = str(Path(output_dir) / f"{Path(light_paths[index]).stem}_calibrada.fits")
                save_fits_image(out_path, frame.calibrated.data, header=headers[index])
                output_paths.append(out_path)

            combined_path = None
            combined_data = None
            if result.combined is not None:
                combined_header = {k: v for k, v in headers[0].items() if k != "EXPTIME"}
                combined_path = str(Path(output_dir) / "combinada.fits")
                save_fits_image(combined_path, result.combined.data, header=combined_header)
                combined_data = result.combined.data

            return SessionReductionOutcome(
                output_paths=tuple(output_paths), combined_path=combined_path, combined_data=combined_data, n_frames=len(result.frames)
            )

        self.run_button.setEnabled(False)
        self.status_label.setText(f"Reduciendo {len(light_paths)} LIGHT(s)...")
        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, outcome: SessionReductionOutcome) -> None:
        self.run_button.setEnabled(True)
        self.status_label.setText("")
        self.session_reduced.emit(outcome)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
        QMessageBox.critical(self, "Reducir sesión de LIGHTS", message)
