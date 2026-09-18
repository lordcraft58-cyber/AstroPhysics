"""Biblioteca en memoria de fotogramas maestros construidos (o cargados
desde disco) en esta sesión -- lo que permite que "Aplicar calibración"
ofrezca elegir, por nombre, un bias/dark/flat ya combinado en vez de
tener que repetir la combinación cada vez.

No es una base de datos: cada entrada, si se guardó, apunta a un FITS
real en disco (escrito por `BuildMasterFrameDialog` vía
`master_frames.save_master_frame`); "reutilizable en sesiones
posteriores" significa reabrir ese FITS real (`Reducción -> Cargar
fotograma maestro...`), no un índice propio persistido aparte.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from PySide6.QtCore import QObject, Signal

from astrophysics_suite.reduction.master_frames import MasterFrame


@dataclass(frozen=True)
class NamedMasterFrame:
    name: str
    frame: MasterFrame
    path: str | None = None
    """Ruta real en disco si ya se guardó/cargó; `None` si solo existe en
    memoria (recién combinado, todavía sin guardar) -- nunca una ruta
    inventada."""
    saved_at: datetime | None = None


class MasterFrameLibrary(QObject):
    changed = Signal()

    def __init__(self, parent=None):
        super().__init__(parent)
        self._entries: dict[str, NamedMasterFrame] = {}

    def add(self, name: str, frame: MasterFrame, *, path: str | None = None, saved_at: datetime | None = None) -> None:
        self._entries[name] = NamedMasterFrame(name=name, frame=frame, path=path, saved_at=saved_at)
        self.changed.emit()

    def get(self, name: str) -> MasterFrame:
        return self._entries[name].frame

    def entry(self, name: str) -> NamedMasterFrame:
        return self._entries[name]

    def entries(self) -> list[NamedMasterFrame]:
        return list(self._entries.values())

    def names_for_kind(self, kind: str) -> list[str]:
        return [name for name, entry in self._entries.items() if entry.frame.kind == kind]

    def all_names(self) -> list[str]:
        return list(self._entries.keys())

    def __len__(self) -> int:
        return len(self._entries)
