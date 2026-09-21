"""Asistente de nueva observación: nombre del objetivo + imágenes con su
banda. Deliberadamente simple -- una sola pantalla, sin pasos ocultos;
las opciones técnicas del Discovery Engine viven aparte (ver
`DiscoveryParams`), no aquí. Migrado de `gui/views/new_observation_view.py`
(Fase 8, Tkinter).
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

BAND_OPTIONS = ["OIII", "HA", "NII", "SII", "BROADBAND", "L-QEF", "OTRA"]


class NewObservationDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Nueva observación")
        self.resize(520, 420)
        self._rows: list[tuple[str, QComboBox]] = []

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel("Nombre del objetivo"))
        self.target_edit = QLineEdit()
        layout.addWidget(self.target_edit)

        images_header = QHBoxLayout()
        images_header.addWidget(QLabel("Imágenes"))
        images_header.addStretch(1)
        add_button = QPushButton("+ Añadir imagen...")
        add_button.clicked.connect(self._add_images)
        images_header.addWidget(add_button)
        layout.addLayout(images_header)

        bulk_row = QHBoxLayout()
        bulk_row.addWidget(QLabel("Banda para todas"))
        self.bulk_band_combo = QComboBox()
        self.bulk_band_combo.addItems(BAND_OPTIONS)
        bulk_row.addWidget(self.bulk_band_combo)
        apply_all_button = QPushButton("Aplicar a todas")
        apply_all_button.clicked.connect(self._apply_band_to_all)
        bulk_row.addWidget(apply_all_button)
        bulk_row.addStretch(1)
        layout.addLayout(bulk_row)

        self.image_list = QListWidget()
        layout.addWidget(self.image_list)

        self.auto_plate_solve_check = QCheckBox("Intentar resolución de placa automáticamente si falta WCS")
        self.auto_plate_solve_check.setChecked(True)
        self.auto_plate_solve_check.setToolTip(
            "Para cada imagen sin WCS, detecta estrellas reales y las resuelve contra Gaia antes de analizar "
            "(ver Astrometría -> Resolver placa automáticamente...). Si falla, esa imagen sigue el análisis sin "
            "coordenadas celestes -- nunca se inventa un WCS."
        )
        layout.addWidget(self.auto_plate_solve_check)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        self.button_box.button(QDialogButtonBox.StandardButton.Ok).setText("Analizar")
        self.button_box.accepted.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _add_images(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(self, "Seleccionar imágenes", "", "FITS/XISF (*.fits *.fit *.fts *.xisf);;FITS (*.fits *.fit *.fts);;XISF (*.xisf);;Todos los archivos (*.*)")
        for path in paths:
            self._add_row(path)
        if paths:
            # las imágenes nuevas nacen ya con la banda elegida arriba -- evita
            # tener que ajustarlas una a una cuando todas comparten filtro,
            # el caso más común al cargar una sesión completa de golpe.
            self._apply_band_to_all()

    def _apply_band_to_all(self) -> None:
        band = self.bulk_band_combo.currentText()
        for _, combo in self._rows:
            combo.setCurrentText(band)

    def _add_row(self, path: str) -> None:
        row_widget = QWidget()
        row_layout = QHBoxLayout(row_widget)
        row_layout.setContentsMargins(4, 2, 4, 2)
        row_layout.addWidget(QLabel(Path(path).name))
        row_layout.addStretch(1)
        band_combo = QComboBox()
        band_combo.addItems(BAND_OPTIONS)
        row_layout.addWidget(band_combo)

        item = QListWidgetItem(self.image_list)
        item.setSizeHint(row_widget.sizeHint())
        item.setData(Qt.ItemDataRole.UserRole, path)
        self.image_list.addItem(item)
        self.image_list.setItemWidget(item, row_widget)
        self._rows.append((path, band_combo))

    def _on_accept(self) -> None:
        if not self.target_edit.text().strip():
            QMessageBox.warning(self, "Nueva observación", "Indica un nombre de objetivo antes de analizar.")
            return
        if not self._rows:
            QMessageBox.warning(self, "Nueva observación", "Añade al menos una imagen antes de analizar.")
            return
        self.accept()

    def result_images(self) -> list[tuple[str, str]]:
        return [(path, combo.currentText()) for path, combo in self._rows]

    def result_target_name(self) -> str:
        return self.target_edit.text().strip()

    def result_auto_plate_solve(self) -> bool:
        return self.auto_plate_solve_check.isChecked()
