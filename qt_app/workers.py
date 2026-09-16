"""Ejecuta un proceso pesado en un hilo de fondo -- mismo principio que
`services/discovery_service.py` en la Fase 8 (nunca bloquear el hilo de
GUI), aquí con el mecanismo nativo de Qt (`QThread` + señales) en vez de
una `queue.Queue` sondeada por `root.after`.
"""
from __future__ import annotations

from typing import Any, Callable

import numpy as np
from PySide6.QtCore import QThread, Signal

from qt_app.processes.base import ProcessResult


class ProcessWorker(QThread):
    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(
        self,
        run_fn: Callable[[np.ndarray, dict[str, Any]], ProcessResult],
        data: np.ndarray,
        params: dict[str, Any],
        parent=None,
    ):
        super().__init__(parent)
        self._run_fn = run_fn
        self._data = data
        self._params = params

    def run(self) -> None:
        try:
            result = self._run_fn(self._data, self._params)
        except Exception as exc:  # noqa: BLE001 -- frontera hilo-de-fondo -> GUI: debe llegar como señal, nunca propagarse
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)


class CallableWorker(QThread):
    """Igual que `ProcessWorker` pero para operaciones que no encajan en
    la firma `(data, params) -> ProcessResult` -- p. ej. construir un
    fotograma maestro a partir de varios archivos, donde la propia carga
    de FITS también debe ocurrir fuera del hilo de GUI."""

    finished_ok = Signal(object)
    failed = Signal(str)

    def __init__(self, fn: Callable[[], Any], parent=None):
        super().__init__(parent)
        self._fn = fn

    def run(self) -> None:
        try:
            result = self._fn()
        except Exception as exc:  # noqa: BLE001 -- frontera hilo-de-fondo -> GUI: debe llegar como señal, nunca propagarse
            self.failed.emit(str(exc))
            return
        self.finished_ok.emit(result)
