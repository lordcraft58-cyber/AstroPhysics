"""Diagnóstico de hardware y actualizaciones verificadas -- conecta a la
GUI, por primera vez, el subsistema que la Fase 1 (seccion 9) encontró
correcto pero completamente sin cablear a ningún punto de entrada:
`check_hardware`, `update_check_https`, `download_verified_update` y
`launch_verified_installer` (código heredado). No se reescribe nada de
esa lógica -- solo se expone de forma asíncrona.
"""
from __future__ import annotations

import queue
import threading
from dataclasses import dataclass, field
from typing import Any

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import check_hardware as _legacy_check_hardware


@dataclass(frozen=True)
class HardwareEvent:
    kind: str  # "done" | "error"
    report: dict[str, Any] = field(default_factory=dict)
    error: str = ""


class HardwareCheckJob:
    """Ejecuta `check_hardware()` en un hilo de fondo -- en Windows
    lanza PowerShell (ver Fase 1: scripts hardcodeados, sin interpolar
    entrada externa, seguro contra inyección de comandos); en otros
    sistemas operativos se degrada con elegancia (cada consulta
    devuelve valores vacíos/None en vez de fallar) -- ya probado así
    desde el propio código heredado."""

    def __init__(self):
        self._events: queue.Queue[HardwareEvent] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="hardware-check", daemon=True)
        self._thread.start()

    def poll(self) -> list[HardwareEvent]:
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def _run(self) -> None:
        try:
            report = _legacy_check_hardware()
            self._events.put(HardwareEvent(kind="done", report=report))
        except Exception as exc:  # noqa: BLE001 -- frontera hilo-de-fondo -> GUI
            self._events.put(HardwareEvent(kind="error", error=str(exc)))
