"""Curva de luz multiépoca: fotometría diferencial real de una estrella
variable frente a hasta `MAX_COMPARISON_STARS` estrellas de comparación,
sobre N LIGHTS del usuario -- reutiliza el registro de fotogramas por
patrón de estrellas, la fotometría de apertura y el motor de
variabilidad ya cerrados y probados
(`astrophysics_suite.photometry.multi_frame`); orquestación nueva sobre
motores científicos existentes, no un motor nuevo.

Sección propia, deliberadamente separada de "Descubrimiento": ese menú
busca fuentes NUEVAS o anómalas comparando varias tomas del mismo campo
contra un catálogo; aquí el usuario ya conoce el objetivo y elige a mano
su comparación, como un flujo clásico de fotometría de estrella
variable (AAVSO/FotoDif), no de búsqueda automática.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.io.fits_header_reader import parse_date_obs
from astrophysics_suite.io.fits_loader import load_image
from astrophysics_suite.photometry.multi_frame import FrameInput, MultiFrameLightCurveResult, build_multi_frame_light_curve
from astrophysics_suite.reporting.models import DataSeries
from astrophysics_suite.visualization.charts import render_series
from qt_app.processes.registry import _header_positive_float
from qt_app.workers import CallableWorker


class LightCurveDialog(QDialog):
    def __init__(
        self,
        points: list[tuple[float, float]],
        reference_data,
        reference_header: dict | None,
        reference_path: str | None,
        parent=None,
    ):
        super().__init__(parent)
        self.setWindowTitle("Curva de luz multiépoca")
        self.resize(760, 680)
        self._target_xy = points[0]
        self._comparison_xy = points[1:]
        self._extra_paths: list[str] = []
        self._reference = FrameInput(
            label=Path(reference_path).name if reference_path else "fotograma de referencia",
            data=reference_data,
            date_obs=parse_date_obs(reference_header or {}),
            gain_e_per_adu=_header_positive_float(reference_header, "GAIN"),
            read_noise_e=_header_positive_float(reference_header, "RDNOISE") or 0.0,
        )
        self._result: MultiFrameLightCurveResult | None = None
        self._chart_png: bytes | None = None
        self._worker: CallableWorker | None = None

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Variable marcada en ({self._target_xy[0]:.1f}, {self._target_xy[1]:.1f}); "
            f"{len(self._comparison_xy)} estrella(s) de comparación marcada(s) en el fotograma de referencia. "
            "Añade el resto de LIGHTS de la misma variable (el primer clic siempre es la variable; los demás, "
            "hasta 5, la comparación)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        files_header = QHBoxLayout()
        files_header.addWidget(QLabel("Fotogramas"))
        files_header.addStretch(1)
        add_button = QPushButton("+ Añadir LIGHTS...")
        add_button.clicked.connect(self._add_files)
        files_header.addWidget(add_button)
        layout.addLayout(files_header)

        self.file_list = QListWidget()
        self.file_list.addItem(f"{self._reference.label}  (referencia)")
        layout.addWidget(self.file_list)

        form = QFormLayout()
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(1.0, 50.0)
        self.radius_spin.setValue(6.0)
        self.radius_spin.setSuffix(" px")
        form.addRow("Radio de apertura", self.radius_spin)
        self.sky_in_spin = QDoubleSpinBox()
        self.sky_in_spin.setRange(1.0, 100.0)
        self.sky_in_spin.setValue(12.0)
        self.sky_in_spin.setSuffix(" px")
        form.addRow("Cielo -- radio interior", self.sky_in_spin)
        self.sky_out_spin = QDoubleSpinBox()
        self.sky_out_spin.setRange(2.0, 150.0)
        self.sky_out_spin.setValue(18.0)
        self.sky_out_spin.setSuffix(" px")
        form.addRow("Cielo -- radio exterior", self.sky_out_spin)
        layout.addLayout(form)

        self.run_button = QPushButton("Calcular curva de luz")
        self.run_button.clicked.connect(self._on_run)
        layout.addWidget(self.run_button)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.chart_label = QLabel()
        self.chart_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.chart_label.setMinimumHeight(260)
        layout.addWidget(self.chart_label)

        export_row = QHBoxLayout()
        self.save_image_button = QPushButton("Guardar gráfico como imagen...")
        self.save_image_button.setEnabled(False)
        self.save_image_button.clicked.connect(self._save_chart_image)
        export_row.addWidget(self.save_image_button)
        self.export_csv_button = QPushButton("Exportar tabla a CSV...")
        self.export_csv_button.setEnabled(False)
        self.export_csv_button.clicked.connect(self._export_csv)
        export_row.addWidget(self.export_csv_button)
        layout.addLayout(export_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    # ---------------------------------------------------------------- fotogramas
    def _add_files(self) -> None:
        paths, _ = QFileDialog.getOpenFileNames(
            self, "Añadir LIGHTS", "", "FITS/XISF (*.fits *.fit *.fts *.xisf);;Todos los archivos (*.*)"
        )
        for path in paths:
            self._extra_paths.append(path)
            self.file_list.addItem(Path(path).name)

    # ---------------------------------------------------------------- cálculo
    def _on_run(self) -> None:
        if not self._comparison_xy:
            QMessageBox.warning(self, "Curva de luz", "Hace falta al menos una estrella de comparación.")
            return
        self.run_button.setEnabled(False)
        self.status_label.setText(f"Calculando sobre {1 + len(self._extra_paths)} fotograma(s)...")

        reference = self._reference
        extra_paths = list(self._extra_paths)
        target_xy = self._target_xy
        comparison_xy = list(self._comparison_xy)
        aperture_radius_px = self.radius_spin.value()
        sky_r_in = self.sky_in_spin.value()
        sky_r_out = self.sky_out_spin.value()

        def _load_and_run() -> MultiFrameLightCurveResult:
            frames = [reference]
            for path in extra_paths:
                loaded = load_image(path, band="")
                header = loaded.legacy_image.header or {}
                frames.append(FrameInput(
                    label=Path(path).name,
                    data=loaded.legacy_image.data,
                    date_obs=parse_date_obs(header),
                    gain_e_per_adu=_header_positive_float(header, "GAIN"),
                    read_noise_e=_header_positive_float(header, "RDNOISE") or 0.0,
                ))
            return build_multi_frame_light_curve(
                frames, target_xy=target_xy, comparison_xy=comparison_xy,
                detection_id="VARSTAR-GUI", aperture_radius_px=aperture_radius_px,
                sky_r_in=sky_r_in, sky_r_out=sky_r_out,
            )

        self._worker = CallableWorker(_load_and_run, self)
        self._worker.finished_ok.connect(self._on_finished)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_finished(self, result: MultiFrameLightCurveResult) -> None:
        self.run_button.setEnabled(True)
        self._result = result
        evidence = result.temporal_evidence

        lines = [f"{result.n_valid_epochs}/{len(result.points)} época(s) con medida válida."]
        for point in result.points:
            if point.skip_reason:
                lines.append(f"  {point.label}: descartado -- {point.skip_reason}")
        if evidence.n_epochs >= 3:
            lines.append(f"¿Variable? {'SÍ' if evidence.variable_candidate else 'no'}")
            if evidence.brightness_change is not None:
                lines.append(
                    f"Cambio de brillo: {evidence.brightness_change.value:+.5f} ± "
                    f"{evidence.brightness_change.error:.5f} mag/hora"
                )
        else:
            lines.append(f"Épocas insuficientes para el ajuste de variabilidad ({evidence.n_epochs} válida(s), hacen falta >= 3).")
        self.status_label.setText("\n".join(lines))

        if evidence.epochs:
            series = DataSeries(
                name="Curva de luz", x=tuple(e.time for e in evidence.epochs), y=tuple(e.value for e in evidence.epochs),
                x_label="Horas desde el primer fotograma", y_label="Magnitud diferencial", y_unit="mag",
                y_error=tuple(e.error if e.error is not None else 0.0 for e in evidence.epochs), kind="line",
            )
            self._chart_png = render_series(series, title="Curva de luz -- estrella variable")
            pixmap = QPixmap()
            pixmap.loadFromData(self._chart_png)
            self.chart_label.setPixmap(pixmap)
            self.save_image_button.setEnabled(True)
        self.export_csv_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.run_button.setEnabled(True)
        self.status_label.setText(f"El cálculo falló: {message}")

    # ---------------------------------------------------------------- exportar
    def _save_chart_image(self) -> None:
        if self._chart_png is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar gráfico", "curva_de_luz.png", "PNG (*.png)")
        if not path:
            return
        Path(path).write_bytes(self._chart_png)
        self.status_label.setText(f"{self.status_label.text()}\nGráfico guardado en {path}")

    def _export_csv(self) -> None:
        if self._result is None:
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar tabla a CSV", "curva_de_luz.csv", "CSV (*.csv)")
        if not path:
            return
        self._result.table.to_csv(path)
        self.status_label.setText(f"{self.status_label.text()}\nTabla exportada a {path}")

    def result_table(self):
        return self._result.table if self._result is not None else None
