"""Puente entre el `logging` de los motores científicos y la GUI.

Revive la idea de `_QueueLogHandler` (código heredado, eliminado en la
Fase 3 junto con `launch_gui_legacy` porque era la única función que lo
usaba) -- pero como una pieza reutilizable de `services/`, no atada a
ninguna GUI concreta. La Fase 5 encontró que `launch_gui()` activa no
conectaba ningún handler de logging: los `LOG.info`/`LOG.warning` que los
motores producen no llegaban a ningún sitio visible en un build sin
consola. Esto lo corrige desde el diseño, no como un parche.
"""
from __future__ import annotations

import logging
import queue


class GuiLogBridge(logging.Handler):
    """Handler de `logging` que empuja cada registro a una `queue.Queue`
    thread-safe. La GUI consume la cola desde el hilo principal (p. ej.
    vía `root.after`), nunca al revés -- por eso esto no depende de
    tkinter en absoluto y vive en `services/`, no en `gui/`."""

    def __init__(self, level: int = logging.INFO):
        super().__init__(level=level)
        self.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s", "%H:%M:%S"))
        self.queue: queue.Queue[str] = queue.Queue()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            self.queue.put(self.format(record))
        except Exception:
            pass

    def drain(self) -> list[str]:
        """Vacía y devuelve todos los mensajes acumulados desde la última
        llamada -- pensado para llamarse periódicamente desde `root.after`."""
        lines = []
        while True:
            try:
                lines.append(self.queue.get_nowait())
            except queue.Empty:
                break
        return lines

    def attach(self, logger_name: str = "aps") -> None:
        """Se conecta al logger que usan los motores heredados (`LOG =
        logging.getLogger("aps")` en legacy/...) y a la raíz, para no
        perderse nada que un motor nuevo registre bajo otro nombre."""
        logging.getLogger(logger_name).addHandler(self)
        logging.getLogger().addHandler(self)

    def detach(self, logger_name: str = "aps") -> None:
        logging.getLogger(logger_name).removeHandler(self)
        logging.getLogger().removeHandler(self)
