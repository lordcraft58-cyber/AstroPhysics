"""Estado de la sesión: el proyecto en memoria que la GUI muestra y
modifica. Persistencia real a disco (usando `astrophysics_suite.models.
project.Project`) queda para una fase posterior -- ver
docs/audit/10-FASE8-GUI.md, seccion "Qué queda". Esta clase ya está
estructurada para que añadir guardar/cargar no requiera un rediseño: es
la única fuente de verdad de "qué hay en el proyecto ahora mismo".
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation


@dataclass
class SessionState:
    project_name: str = "Proyecto sin guardar"
    observations: list[Observation] = field(default_factory=list)
    loaded_images: dict[str, LoadedImage] = field(default_factory=dict)
    """Clave: ImageRef.path. Compartido entre todas las observaciones de
    la sesión para no releer el mismo archivo dos veces."""
    candidates: list[Candidate] = field(default_factory=list)
    _listeners: list = field(default_factory=list, repr=False)
    _lock: threading.Lock = field(default_factory=threading.Lock, repr=False)

    def on_change(self, callback) -> None:
        """Registra un callback (sin argumentos) a llamar cada vez que el
        estado cambia. La GUI lo usa para refrescar vistas sin acoplarse
        a los detalles de qué cambió."""
        self._listeners.append(callback)

    def _notify(self) -> None:
        for callback in list(self._listeners):
            callback()

    def add_observation(self, observation: Observation, loaded_images: dict[str, LoadedImage]) -> None:
        with self._lock:
            self.observations.append(observation)
            self.loaded_images.update(loaded_images)
        self._notify()

    def add_candidates(self, candidates: list[Candidate]) -> None:
        with self._lock:
            self.candidates.extend(candidates)
        self._notify()

    def replace_candidate(self, updated: Candidate) -> None:
        """Sustituye un Candidate por su versión revisada (ver
        `Candidate.mark_reviewed`, que devuelve una instancia nueva en vez
        de mutar -- este método es el único sitio donde la lista de
        candidatos "olvida" la versión anterior, y solo porque
        `review_notes` ya conserva el historial completo dentro del
        propio Candidate nuevo)."""
        with self._lock:
            for index, candidate in enumerate(self.candidates):
                if candidate.candidate_id == updated.candidate_id:
                    self.candidates[index] = updated
                    break
        self._notify()

    def candidates_pending_review(self) -> list[Candidate]:
        return [c for c in self.candidates if c.review_state.value == "PENDING"]

    @property
    def created_at(self) -> datetime:
        return datetime.now(timezone.utc)
