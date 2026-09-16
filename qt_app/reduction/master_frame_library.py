"""Biblioteca en memoria de fotogramas maestros construidos en esta
sesión -- lo que permite que "Aplicar calibración" ofrezca elegir, por
nombre, un bias/dark/flat ya combinado en vez de tener que repetir la
combinación cada vez.
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import QObject, Signal

from astrophysics_suite.reduction.master_frames import MasterFrame


@dataclass(frozen=True)
class NamedMasterFrame:
    name: str
    frame: MasterFrame


class MasterFrameLibrary(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: dict[str, NamedMasterFrame] = {}

    def add(self, name: str, frame: MasterFrame) -> None:
        self._entries[name] = NamedMasterFrame(name=name, frame=frame)
        self.changed.emit()

    def get(self, name: str) -> MasterFrame:
        return self._entries[name].frame

    def names_for_kind(self, kind: str) -> list[str]:
        return [name for name, entry in self._entries.items() if entry.frame.kind == kind]

    def all_names(self) -> list[str]:
        return list(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)
