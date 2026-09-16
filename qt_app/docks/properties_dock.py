"""Panel de propiedades -- formulario de parámetros del proceso
seleccionado, generado dinámicamente desde `ProcessDefinition.
parameters`. "Aplicar" es lo único que dispara la ejecución real (en un
hilo de fondo, ver `workers.py`) -- nunca al simplemente seleccionar o
arrastrar un proceso.
"""
from __future__ import annotations

from typing import Any

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from qt_app.processes.base import ProcessDefinition


class PropertiesDock(QWidget):
    run_requested = Signal(str, dict)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.current_process: ProcessDefinition | None = None
        self._param_widgets: dict[str, QWidget] = {}

        self._layout = QVBoxLayout(self)
        self.title_label = QLabel("Ningún proceso seleccionado")
        self.title_label.setObjectName("SectionHeading")
        self.title_label.setWordWrap(True)
        self._layout.addWidget(self.title_label)

        self.description_label = QLabel("")
        self.description_label.setObjectName("Muted")
        self.description_label.setWordWrap(True)
        self._layout.addWidget(self.description_label)

        self.form_container = QWidget(self)
        self.form_layout = QFormLayout(self.form_container)
        self._layout.addWidget(self.form_container)

        self.apply_button = QPushButton("Aplicar")
        self.apply_button.setObjectName("Accent")
        self.apply_button.clicked.connect(self._on_apply_clicked)
        self._layout.addWidget(self.apply_button)
        self._layout.addStretch(1)

        self.set_process(None)

    def set_process(self, process: ProcessDefinition | None) -> None:
        self.current_process = process
        self._clear_form()

        if process is None:
            self.title_label.setText("Ningún proceso seleccionado")
            self.description_label.setText("Elige un proceso del explorador.")
            self.apply_button.setEnabled(False)
            return

        self.title_label.setText(process.name)
        self.description_label.setText(process.description)

        if not process.is_wired:
            self.apply_button.setEnabled(False)
            self.apply_button.setToolTip("Este proceso todavía no está cableado a una implementación real.")
            return

        self.apply_button.setEnabled(True)
        self.apply_button.setToolTip("")
        for spec in process.parameters:
            widget = self._build_widget(spec)
            self._param_widgets[spec.name] = widget
            self.form_layout.addRow(spec.label, widget)

    def _build_widget(self, spec) -> QWidget:
        if spec.kind == "bool":
            widget = QCheckBox()
            widget.setChecked(bool(spec.default))
            return widget
        if spec.kind == "int":
            widget = QSpinBox()
            widget.setMinimum(int(spec.minimum) if spec.minimum is not None else -1_000_000)
            widget.setMaximum(int(spec.maximum) if spec.maximum is not None else 1_000_000)
            widget.setValue(int(spec.default))
            return widget
        widget = QDoubleSpinBox()
        widget.setDecimals(spec.decimals)
        widget.setMinimum(float(spec.minimum) if spec.minimum is not None else -1e9)
        widget.setMaximum(float(spec.maximum) if spec.maximum is not None else 1e9)
        widget.setValue(float(spec.default))
        return widget

    def _clear_form(self) -> None:
        while self.form_layout.rowCount():
            self.form_layout.removeRow(0)
        self._param_widgets.clear()

    def _on_apply_clicked(self) -> None:
        if self.current_process is None or not self.current_process.is_wired:
            return
        params: dict[str, Any] = {}
        for spec in self.current_process.parameters:
            widget = self._param_widgets[spec.name]
            if spec.kind == "bool":
                params[spec.name] = widget.isChecked()
            elif spec.kind == "int":
                params[spec.name] = widget.value()
            else:
                params[spec.name] = widget.value()
        self.run_requested.emit(self.current_process.process_id, params)
