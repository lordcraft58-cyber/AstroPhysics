"""Construcción de fotogramas maestros de calibración (bias/dark/flat)
desde varios archivos a la vez -- equivalente propio de `zerocombine`/
`darkcombine`/`flatcombine` de IRAF, expuesto en el taller Qt.

El resultado se escribe siempre a un FITS real en la ruta que elige el
usuario (nunca solo en memoria): "Salida" + "Examinar..." abren un
selector de archivos real de Qt/Windows, se recuerda la última carpeta
usada entre construcciones, y se confirma antes de sobrescribir un
archivo existente.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.reduction.master_frames import build_master_bias, build_master_dark, build_master_flat, save_master_frame
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.workers import CallableWorker
from services.app_preferences import AppPreferencesStore

NONE_OPTION = "(ninguno)"
KIND_OPTIONS = {"Bias": "bias", "Dark": "dark", "Flat": "flat"}
_LAST_OUTPUT_DIR_KEY = "last_master_frame_dir"
_FITS_EXTENSIONS = (".fits", ".fit", ".fts")


class BuildMasterFrameDialog(QDialog):
    def __init__(self, library: MasterFrameLibrary, parent=None, *, preferences: AppPreferencesStore | None = None):
        super().__init__(parent)
        self.library = library
        self.preferences = preferences or AppPreferencesStore()
        self.setWindowTitle("Construir fotograma maestro")
        self.resize(520, 540)
        self._worker: CallableWorker | None = None
        self._output_path_edited_by_user = False

        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.kind_combo = QComboBox()
        self.kind_combo.addItems(list(KIND_OPTIONS.keys()))
        self.kind_combo.currentTextChanged.connect(self._update_visibility)
        self.kind_combo.currentTextChanged.connect(self._update_default_output_path)
        form.addRow("Tipo", self.kind_combo)

        self.name_edit = QLineEdit()
        self.name_edit.textChanged.connect(self._update_default_output_path)
        form.addRow("Nombre", self.name_edit)

        self.exposure_spin = QDoubleSpinBox()
        self.exposure_spin.setRange(0.001, 36000.0)
        self.exposure_spin.setValue(60.0)
        self.exposure_spin.setSuffix(" s")
        self.exposure_row_label = QLabel("Tiempo de exposición")
        form.addRow(self.exposure_row_label, self.exposure_spin)

        self.bias_combo = QComboBox()
        self.bias_row_label = QLabel("Bias maestro a restar")
        form.addRow(self.bias_row_label, self.bias_combo)

        self.dark_combo = QComboBox()
        self.dark_row_label = QLabel("Dark maestro a restar")
        form.addRow(self.dark_row_label, self.dark_combo)
        layout.addLayout(form)

        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("Fotogramas de entrada"))
        files_header.addStretch(1)
        add_button = QPushButton("+ Añadir...")
        add_button.clicked.connect(self._add_files)
        files_header.addWidget(add_button)
        layout.addLayout(files_header)

        self.file_list = QListWidget()
        layout.addWidget(self.file_list)

        output_header = QHBoxLayout()
        output_header.addWidget(QLabel("Carpeta/archivo de salida"))
        layout.addLayout(output_header)
        output_row = QHBoxLayout()
        self.output_path_edit = QLineEdit()
        self.output_path_edit.setPlaceholderText("Elige dónde guardar el FITS del fotograma maestro...")
        self.output_path_edit.textEdited.connect(self._on_output_path_edited_by_user)
        output_row.addWidget(self.output_path_edit)
        browse_button = QPushButton("Examinar...")
        browse_button.clicked.connect(self._browse_output_path)
        output_row.addWidget(browse_button)
        layout.addLayout(output_row)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.combine_button = QPushButton("Combinar y guardar")
        self.combine_button.setObjectName("Accent")
        self.combine_button.clicked.connect(self._on_combine)
        self.button_box.addButton(self.combine_button, QDialogButtonBox.ButtonRole.AcceptRole)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._update_visibility(self.kind_combo.currentText())
        self._refresh_master_combos()
        self._update_default_output_path()

    def _refresh_master_combos(self) -> None:
        self.bias_combo.clear()
        self.bias_combo.addItem(NONE_OPTION)
        self.bias_combo.addItems(self.library.names_for_kind("bias"))
        self.dark_combo.clear()
        self.dark_combo.addItem(NONE_OPTION)
        self.dark_combo.addItems(self.library.names_for_kind("dark"))

    def _update_visibility(self, kind_label: str) -> None:
        kind = KIND_OPTIONS[kind_label]
        self.exposure_row_label.setVisible(kind in ("dark", "flat"))
        self.exposure_spin.setVisible(kind in ("dark", "flat"))
        self.exposure_row_label.setText("Tiempo de exposición (dark)" if kind == "dark" else "Tiempo de exposición (flat, si se resta dark)")
        self.bias_row_label.setVisible(kind in ("dark", "flat"))
        self.bias_combo.setVisible(kind in ("dark", "flat"))
        self.dark_row_label.setVisible(kind == "flat")
        self.dark_combo.setVisible(kind == "flat")

    def _on_output_path_edited_by_user(self, _text: str) -> None:
        self._output_path_edited_by_user = True

    def _update_default_output_path(self) -> None:
        """Propone `<última_carpeta_usada>/<nombre>.fits`, pero solo
        mientras el usuario no haya editado la ruta a mano -- nunca pisa
        una elección explícita solo porque cambió el nombre."""
        if self._output_path_edited_by_user:
            return
        name = self.name_edit.text().strip()
        if not name:
            self.output_path_edit.setText("")
            return
        base_dir = self.preferences.get(_LAST_OUTPUT_DIR_KEY) or str(Path.home())
        self.output_path_edit.setText(str(Path(base_dir) / f"{name}.fits"))

    def _browse_output_path(self) -> None:
        proposed = self.output_path_edit.text().strip() or str(Path(self.preferences.get(_LAST_OUTPUT_DIR_KEY) or Path.home()))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar fotograma maestro", proposed, "FITS (*.fits *.fit *.fts)")
        if path:
            self.output_path_edit.setText(path)
            self._output_path_edited_by_user = True

    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar fotogramas", "", "FITS (*.fits *.fit *.fts);;Todos los archivos (*.*)")
        for path in paths:
            self.file_list.addItem(Path(path).name)
            self.file_list.item(self.file_list.count() - 1).setData(Qt.ItemDataRole.UserRole, path)

    def _selected_paths(self) -> list[str]:
        return [self.file_list.item(i).data(Qt.ItemDataRole.UserRole) for i in range(self.file_list.count())]

    def _resolved_output_path(self) -> Path:
        raw = self.output_path_edit.text().strip()
        path = Path(raw)
        if path.suffix.lower() not in _FITS_EXTENSIONS:
            path = path.with_name(path.name + ".fits")
        return path

    def _on_combine(self) -> None:
        if not self.name_edit.text().strip():
            QMessageBox.warning(self, "Construir fotograma maestro", "Indica un nombre para el fotograma maestro.")
            return
        if self.name_edit.text().strip() in self.library.all_names():
            QMessageBox.warning(self, "Construir fotograma maestro", "Ya existe un fotograma maestro con ese nombre.")
            return
        if len(self._selected_paths()) < 3:
            QMessageBox.warning(self, "Construir fotograma maestro", "Se necesitan al menos 3 fotogramas para un rechazo robusto.")
            return
        if not self.output_path_edit.text().strip():
            QMessageBox.warning(self, "Construir fotograma maestro", "Elige una carpeta/archivo de salida (botón «Examinar...»).")
            return

        output_path = self._resolved_output_path()
        if output_path.exists():
            reply = QMessageBox.question(
                self, "Construir fotograma maestro",
                f"Ya existe un archivo en «{output_path}».\n¿Deseas sobrescribirlo?",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No, QMessageBox.StandardButton.No,
            )
            if reply != QMessageBox.StandardButton.Yes:
                return

        kind = KIND_OPTIONS[self.kind_combo.currentText()]
        paths = self._selected_paths()
        exposure_s = self.exposure_spin.value()
        bias_name = self.bias_combo.currentText()
        dark_name = self.dark_combo.currentText()

        def build():
            from astrophysics_suite.io.fits_loader import load_image

            frames = [load_image(p, band="", role="calibration").legacy_image.data for p in paths]
            if kind == "bias":
                return build_master_bias(frames)
            if kind == "dark":
                bias_data = self.library.get(bias_name).data if bias_name != NONE_OPTION else None
                return build_master_dark(frames, exposure_s=exposure_s, master_bias=bias_data)
            bias_data = self.library.get(bias_name).data if bias_name != NONE_OPTION else None
            master_dark = self.library.get(dark_name) if dark_name != NONE_OPTION else None
            flat_exposure = exposure_s if master_dark is not None else None
            return build_master_flat(frames, master_bias=bias_data, master_dark=master_dark, flat_exposure_s=flat_exposure)

        self.combine_button.setEnabled(False)
        self.status_label.setText(f"Combinando {len(paths)} fotograma(s)...")
        self._worker = CallableWorker(build, self)
        self._worker.finished_ok.connect(lambda frame: self._on_combined(frame, output_path))
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_combined(self, master_frame, output_path: Path) -> None:
        try:
            save_master_frame(str(output_path), master_frame)
        except OSError as exc:
            self.combine_button.setEnabled(True)
            self.status_label.setText(f"El fotograma se combinó pero no se pudo guardar en «{output_path}»: {exc}")
            QMessageBox.critical(self, "Construir fotograma maestro", f"No se pudo guardar «{output_path.name}»:\n\n{exc}")
            return

        self.preferences.set(_LAST_OUTPUT_DIR_KEY, str(output_path.parent))
        self.library.add(self.name_edit.text().strip(), master_frame, path=str(output_path), saved_at=datetime.now(timezone.utc))
        self.status_label.setText("")
        self.combine_button.setEnabled(True)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.combine_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
