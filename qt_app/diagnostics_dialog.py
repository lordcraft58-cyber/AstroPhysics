"""Diagnóstico de equipo -- conecta al taller Qt el mismo
`services/hardware_service.py` que la Fase 8 conectó por primera vez a
una GUI (la Fase 1 lo había encontrado correcto pero completamente sin
cablear a ningún punto de entrada). Sondeado por `QTimer`, igual que
`DiscoveryJob` en `main_window.py` -- el servicio en sí no cambia.
"""
from __future__ import annotations

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QDialog, QFormLayout, QLabel, QPushButton, QVBoxLayout

from services.hardware_service import HardwareCheckJob

POLL_MS = 150


class DiagnosticsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Diagnóstico de equipo")
        self.resize(480, 420)
        self._job: HardwareCheckJob | None = None
        self._timer: QTimer | None = None

        layout = QVBoxLayout(self)
        self.run_button = QPushButton("Analizar este equipo")
        self.run_button.clicked.connect(self._run)
        layout.addWidget(self.run_button)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.form = QFormLayout()
        layout.addLayout(self.form)

        self.recommendations_label = QLabel("")
        self.recommendations_label.setWordWrap(True)
        layout.addWidget(self.recommendations_label)
        layout.addStretch(1)

    def _run(self) -> None:
        self.run_button.setEnabled(False)
        self.status_label.setText("Analizando…")
        self._job = HardwareCheckJob()
        self._job.start()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._poll)
        self._timer.start(POLL_MS)

    def _poll(self) -> None:
        if self._job is None:
            return
        for event in self._job.poll():
            self.run_button.setEnabled(True)
            self.status_label.setText("")
            if event.kind == "done":
                self._render_report(event.report)
            elif event.kind == "error":
                self.status_label.setText(f"No se pudo completar el diagnóstico: {event.error}")
            self._stop_polling()
            return

    def _stop_polling(self) -> None:
        if self._timer is not None:
            self._timer.stop()
            self._timer = None
        self._job = None

    def _clear_form(self) -> None:
        while self.form.rowCount():
            self.form.removeRow(0)

    def _render_report(self, report: dict) -> None:
        self._clear_form()
        ram_gb = report.get("ram_gb")
        self.form.addRow("RAM", QLabel(f"{ram_gb:.1f} GB" if ram_gb is not None else "—"))
        free_gb = report.get("free_disk_gb")
        self.form.addRow("Disco libre", QLabel(f"{free_gb:.0f} GB" if free_gb is not None else "—"))
        self.form.addRow("GPU", QLabel(report.get("gpu_names") or "—"))
        torch_info = report.get("torch", {})
        cuda_text = "CUDA" if torch_info.get("cuda") else ("CPU" if torch_info.get("available") else "no disponible")
        self.form.addRow("AstroVision", QLabel(cuda_text))
        self.form.addRow("Cámara ZWO ASI detectada", QLabel("Sí" if report.get("zwo_asi_detected") else "No"))
        cpu = report.get("cpu") or {}
        if cpu.get("Name"):
            self.form.addRow("CPU", QLabel(str(cpu.get("Name"))))

        recommendations = report.get("recommendations") or []
        if recommendations:
            self.recommendations_label.setText("Recomendaciones:\n" + "\n".join(f"·  {r}" for r in recommendations))
        else:
            self.recommendations_label.setText("")
