"""Ejecuta el Discovery Engine (`astrophysics_suite.discovery.pipeline`)
en un hilo de fondo, con progreso y cancelación -- para que la GUI nunca
se congele durante un análisis (ver el encargo original: "las
operaciones pesadas deben ejecutarse en trabajadores apropiados, con
progreso, registros, cancelación segura y manejo de errores").

Patrón: el hilo de fondo solo escribe a una `queue.Queue`; el hilo
principal (GUI) es el único que la lee, vía `poll()` llamado
periódicamente desde `root.after`. Es el mismo patrón que ya usaba
correctamente `legacy...launch_gui()` (ver docs/audit/01-..., seccion
10) -- aquí generalizado para cualquier llamador, no reescrito desde
cero.
"""
from __future__ import annotations

import queue
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone

from astrophysics_suite.discovery.pipeline import DiscoveryCancelled, DiscoveryRunSummary, run_generic_discovery
from astrophysics_suite.io.fits_loader import LoadedImage, build_observation
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation


@dataclass(frozen=True)
class DiscoveryParams:
    fwhm_px: float = 3.0
    threshold_sigma: float = 5.0
    max_sources: int = 3000
    match_radius_arcsec: float = 3.0
    gaia_mag_limit: float = 20.0
    auto_plate_solve: bool = True
    """Si una imagen no trae WCS, intentar resolución automática de placa
    antes de detectar/identificar fuentes (ver `discovery.pipeline.
    _ensure_wcs`) -- desactivable desde "Nueva observación" cuando el
    usuario prefiere el flujo manual ("Ajustar WCS manualmente...")."""


@dataclass(frozen=True)
class JobEvent:
    kind: str  # "progress" | "done" | "cancelled" | "error"
    fraction: float = 0.0
    message: str = ""
    observation: Observation | None = None
    loaded_images: dict[str, LoadedImage] = field(default_factory=dict)
    candidates: tuple[Candidate, ...] = ()
    summary: DiscoveryRunSummary | None = None
    error: BaseException | None = None


class DiscoveryJob:
    """Un análisis en curso: carga las imágenes seleccionadas, construye
    la `Observation` y ejecuta `run_generic_discovery` -- todo en un
    único hilo de fondo, porque ambos pasos tocan disco/red y pueden
    tardar."""

    def __init__(
        self,
        *,
        target_name: str,
        images: list[tuple[str, str]],
        params: DiscoveryParams = DiscoveryParams(),
        pipeline_version: str = "",
    ):
        self.job_id = str(uuid.uuid4())
        self._target_name = target_name
        self._images = images
        self._params = params
        self._pipeline_version = pipeline_version
        self._cancel_event = threading.Event()
        self._events: queue.Queue[JobEvent] = queue.Queue()
        self._thread: threading.Thread | None = None

    def start(self) -> None:
        self._thread = threading.Thread(target=self._run, name="discovery-job", daemon=True)
        self._thread.start()

    def cancel(self) -> None:
        self._cancel_event.set()

    def poll(self) -> list[JobEvent]:
        """Eventos nuevos desde la última llamada. Debe llamarse desde el
        hilo principal (p. ej. `root.after(100, ...)`)."""
        events = []
        while True:
            try:
                events.append(self._events.get_nowait())
            except queue.Empty:
                break
        return events

    def _report(self, fraction: float, message: str) -> None:
        self._events.put(JobEvent(kind="progress", fraction=fraction, message=message))

    def _run(self) -> None:
        try:
            self._report(0.0, f"Cargando {len(self._images)} imagen(es)...")
            observation_id = f"OBS-{uuid.uuid4().hex[:8].upper()}"
            observation, loaded_images = build_observation(
                self._images,
                observation_id=observation_id,
                target_name=self._target_name,
                created_at=datetime.now(timezone.utc),
            )
            if self._cancel_event.is_set():
                raise DiscoveryCancelled("Análisis cancelado por el usuario")

            candidates, summary = run_generic_discovery(
                observation,
                loaded_images,
                fwhm_px=self._params.fwhm_px,
                threshold_sigma=self._params.threshold_sigma,
                max_sources=self._params.max_sources,
                match_radius_arcsec=self._params.match_radius_arcsec,
                gaia_mag_limit=self._params.gaia_mag_limit,
                pipeline_version=self._pipeline_version,
                progress=self._report,
                cancel=self._cancel_event,
                auto_plate_solve=self._params.auto_plate_solve,
            )
            self._events.put(
                JobEvent(
                    kind="done",
                    fraction=1.0,
                    observation=observation,
                    loaded_images=loaded_images,
                    candidates=tuple(candidates),
                    summary=summary,
                )
            )
        except DiscoveryCancelled:
            self._events.put(JobEvent(kind="cancelled", message="Análisis cancelado"))
        except Exception as exc:  # noqa: BLE001 -- frontera hilo-de-fondo -> GUI: debe llegar como evento, nunca propagarse
            self._events.put(JobEvent(kind="error", message=str(exc), error=exc))
