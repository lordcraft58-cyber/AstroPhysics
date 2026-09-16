"""Consola integrada -- registro en tiempo real de operaciones y
resultados, en la parte inferior del taller (pide el encargo
explícitamente). Puente hacia el módulo `logging` estándar de Python,
igual que `services/logging_bridge.py` hacía para la GUI en Tkinter,
pero emitiendo directamente por señal Qt (segura entre hilos) en vez de
por una `queue.Queue` sondeada.
"""
from __future__ import annotations

import logging

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QPlainTextEdit, QVBoxLayout, QWidget


class _QtLogBridge(QObject, logging.Handler):
    message_logged = Signal(str)

    def __init__(self):
        QObject.__init__(self)
        logging.Handler.__init__(self)
        self.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-7s  %(message)s", datefmt="%H:%M:%S"))

    def emit(self, record: logging.LogRecord) -> None:
        self.message_logged.emit(self.format(record))


class ConsoleDock(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.text = QPlainTextEdit(self)
        self.text.setReadOnly(True)
        self.text.setMaximumBlockCount(5000)
        layout.addWidget(self.text)

        self._bridge = _QtLogBridge()
        self._bridge.message_logged.connect(self.text.appendPlainText)
        root_logger = logging.getLogger()
        root_logger.addHandler(self._bridge)
        # la consola debe funcionar por sí sola: si nada (p. ej. un
        # `__main__.py` distinto, o ninguno) configuró ya el logger raíz,
        # su nivel por defecto es WARNING y los `logger.info(...)` de
        # main_window.py nunca llegarían a este handler -- se baja el
        # nivel aquí, pero nunca se sube uno ya más verboso (DEBUG) que
        # alguien haya pedido explícitamente.
        if root_logger.level == logging.NOTSET or root_logger.level > logging.INFO:
            root_logger.setLevel(logging.INFO)

    def log(self, message: str) -> None:
        self.text.appendPlainText(message)

    def closeEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        logging.getLogger().removeHandler(self._bridge)
        super().closeEvent(event)
