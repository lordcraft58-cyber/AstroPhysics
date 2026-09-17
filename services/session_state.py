"""Estado de la sesión: el proyecto en memoria que la GUI muestra y
modifica. Persistencia real a disco -- `astrophysics_suite.io.session_
export.save_session`/`load_session`, cableada en `qt_app/main_window.py`
("Archivo -> Guardar sesión.../Abrir sesión...") -- cierra el hueco que
este mismo docstring documentaba como pendiente ("queda para una fase
posterior"; ver docs/audit/39-CIERRE-MOTOR-CALIBRACION-FOTOMETRICA.md y
el cierre del motor de persistencia de sesión que lo resolvió). Esta
clase ya estaba estructurada para que añadir guardar/cargar no
requiriera un rediseño: es la única fuente de verdad de "qué hay en el
proyecto ahora mismo".
"""
from __future__ import annotations

import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone

from astrophysics_suite.astrometry.wcs_fit import WCSSolution
from astrophysics_suite.io.fits_loader import LoadedImage
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation
from astrophysics_suite.photometry.calibration import ZeropointFit


@dataclass
class SessionState:
    project_name: str = "Proyecto sin guardar"
    observations: list[Observation] = field(default_factory=list)
    loaded_images: dict[str, LoadedImage] = field(default_factory=dict)
    """Clave: ImageRef.path. Compartido entre todas las observaciones de
    la sesión para no releer el mismo archivo dos veces."""
    candidates: list[Candidate] = field(default_factory=list)
    wcs_solutions: dict[str, WCSSolution] = field(default_factory=dict)
    """Clave: `ImageView.source_path` real de la imagen ajustada -- el
    último `WCSSolution` real (de "Ajustar WCS...", resolución automática
    o ciega) para esa imagen en esta sesión de GUI. Transitorio: no se
    persiste con `io.session_export` (es un resultado por imagen, no
    parte de ningún `Candidate`/`Observation`), pero mientras la sesión
    sigue abierta permite que "Generar informe científico..." muestre
    residuales reales en vez de NO DISPONIBLE."""
    zeropoint_fits: dict[str, ZeropointFit] = field(default_factory=dict)
    """Mismo patrón que `wcs_solutions`, para el último `ZeropointFit`
    real de `photometry.zeropoint` sobre esa imagen."""
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

    def load_saved_session(self, *, project_name: str, observations: list[Observation], candidates: list[Candidate]) -> None:
        """Incorpora una sesión leída de disco (`io.session_export.
        load_session`) a la sesión en memoria actual -- SUMA, nunca
        reemplaza: igual que "Nueva observación..." nunca vació lo que
        ya había, "Abrir sesión..." nunca descarta análisis en curso sin
        que el usuario lo pida explícitamente. `loaded_images` queda
        vacío para las observaciones restauradas -- una sesión guardada
        no incluye los píxeles originales (solo la ruta del FITS de
        origen en cada `ImageRef`), así que una imagen de una sesión
        reabierta debe reabrirse desde disco para volver a verse; los
        candidatos y su cadena de evidencia completa sí llegan
        íntegros, con independencia de esto."""
        with self._lock:
            if project_name:
                self.project_name = project_name
            self.observations.extend(observations)
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

    def set_wcs_solution(self, path: str, solution: WCSSolution) -> None:
        with self._lock:
            self.wcs_solutions[path] = solution

    def set_zeropoint_fit(self, path: str, fit: ZeropointFit) -> None:
        with self._lock:
            self.zeropoint_fits[path] = fit

    def candidates_pending_review(self) -> list[Candidate]:
        return [c for c in self.candidates if c.review_state.value == "PENDING"]

    @property
    def created_at(self) -> datetime:
        return datetime.now(timezone.utc)
