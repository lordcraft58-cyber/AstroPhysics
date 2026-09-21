"""Agrupación multiépoca: de N detecciones sueltas a UNA fuente física
observada N veces.

## El problema real que resuelve

Sin esto, Discovery trata cada FITS como una imagen independiente: con 3
lights del mismo campo produce 3 veces los mismos candidatos duplicados
y no sabe que son el mismo objeto. Medido sobre los 3 lights reales de
M 31 del usuario: 416 / 412 / 492 detecciones por época, de las que solo
~300 tienen contrapartida entre épocas. Ni la variabilidad ni el
movimiento propio son calculables sin agrupar primero.

## Cómo agrupa (y por qué así)

El emparejamiento es por **coordenadas celestes reales**, no por píxel:
entre épocas hay dithering (las tres tomas de M 31 están desplazadas
entre sí), así que el mismo objeto cae en píxeles distintos. Sin WCS no
se puede agrupar, y eso se declara explícitamente en vez de emparejar
por píxel y producir trayectorias falsas.

Un `SourceTrack` con una sola época es un resultado válido y muy
informativo: una fuente que aparece en una sola época es exactamente el
candidato a transitorio, asteroide, rayo cósmico o artefacto que
interesa mirar -- no se descarta.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import datetime

import numpy as np

from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg
from astrophysics_suite.models.detection import Detection

ENGINE_NAME = "discovery.source_tracks"
ENGINE_VERSION = "1.0"

DEFAULT_MATCH_RADIUS_ARCSEC = 2.0


@dataclass(frozen=True)
class EpochDetection:
    """Una detección situada en su época real."""

    epoch_index: int
    epoch_time: datetime | None
    band: str
    image_path: str
    detection: Detection


@dataclass
class SourceTrack:
    """La misma fuente física observada en una o varias épocas."""

    track_id: str
    observations: list[EpochDetection] = field(default_factory=list)

    @property
    def n_epochs(self) -> int:
        return len({obs.epoch_index for obs in self.observations})

    @property
    def bands(self) -> tuple[str, ...]:
        return tuple(sorted({obs.band for obs in self.observations}))

    @property
    def reference(self) -> EpochDetection:
        """La observación de referencia: la de mayor S/N, que es la mejor
        medida de la posición y la forma de la fuente."""
        return max(self.observations, key=lambda obs: obs.detection.peak_snr)

    @property
    def has_sky_coordinates(self) -> bool:
        return all(obs.detection.position.has_sky_coordinates for obs in self.observations)

    def sky_positions(self) -> list[tuple[datetime | None, float, float]]:
        return [
            (obs.epoch_time, obs.detection.position.ra_deg, obs.detection.position.dec_deg)
            for obs in sorted(self.observations, key=lambda o: o.epoch_index)
            if obs.detection.position.has_sky_coordinates
        ]

    def position_scatter_arcsec(self) -> float | None:
        """Dispersión real de la posición entre épocas -- la usa el motor
        de artefactos para distinguir un error de registro de un
        movimiento real."""
        positions = self.sky_positions()
        if len(positions) < 2:
            return None
        ra = np.array([p[1] for p in positions], dtype=float)
        dec = np.array([p[2] for p in positions], dtype=float)
        mean_dec = float(np.mean(dec))
        dx = (ra - np.mean(ra)) * math.cos(math.radians(mean_dec)) * 3600.0
        dy = (dec - np.mean(dec)) * 3600.0
        return float(np.sqrt(np.mean(dx**2 + dy**2)))


@dataclass(frozen=True)
class TrackingResult:
    tracks: tuple[SourceTrack, ...]
    n_epochs: int
    ungrouped_reason: str = ""
    """Motivo por el que NO se pudo agrupar, si aplica -- vacío cuando el
    agrupamiento se hizo de verdad."""

    @property
    def grouped(self) -> bool:
        return not self.ungrouped_reason

    @property
    def multi_epoch_tracks(self) -> tuple[SourceTrack, ...]:
        return tuple(track for track in self.tracks if track.n_epochs > 1)


def group_detections_into_tracks(
    epoch_detections: list[EpochDetection],
    *,
    match_radius_arcsec: float = DEFAULT_MATCH_RADIUS_ARCSEC,
    observation_id: str = "",
) -> TrackingResult:
    """Agrupa detecciones de varias épocas en fuentes físicas.

    Si alguna detección no tiene coordenadas celestes, NO se agrupa por
    píxel como sustituto: entre épocas hay dithering y eso produciría
    trayectorias inventadas. Se devuelve cada detección como su propia
    traza de una época, con el motivo explícito."""
    n_epochs = len({obs.epoch_index for obs in epoch_detections})

    with_sky = [obs for obs in epoch_detections if obs.detection.position.has_sky_coordinates]
    if len(with_sky) != len(epoch_detections):
        missing = len(epoch_detections) - len(with_sky)
        return TrackingResult(
            tracks=tuple(
                SourceTrack(track_id=f"{observation_id}-TRK-{index:05d}", observations=[obs])
                for index, obs in enumerate(epoch_detections)
            ),
            n_epochs=n_epochs,
            ungrouped_reason=(
                f"{missing} de {len(epoch_detections)} detecciones no tienen coordenadas celestes: sin WCS no se "
                f"pueden emparejar entre épocas (el dithering mueve la misma fuente a píxeles distintos) y "
                f"emparejar por píxel produciría trayectorias falsas"
            ),
        )

    if n_epochs < 2:
        return TrackingResult(
            tracks=tuple(
                SourceTrack(track_id=f"{observation_id}-TRK-{index:05d}", observations=[obs])
                for index, obs in enumerate(epoch_detections)
            ),
            n_epochs=n_epochs,
            ungrouped_reason="solo hay una época: no hay nada que emparejar entre épocas",
        )

    # Agrupamiento incremental por cercanía angular: cada detección se une a
    # la traza abierta más cercana dentro del radio, o abre una nueva.
    tracks: list[SourceTrack] = []
    centroids: list[tuple[float, float]] = []

    for obs in sorted(epoch_detections, key=lambda o: (o.epoch_index, -o.detection.peak_snr)):
        ra = obs.detection.position.ra_deg
        dec = obs.detection.position.dec_deg
        best_index, best_separation = -1, float("inf")
        for index, (track_ra, track_dec) in enumerate(centroids):
            # Una traza no puede contener dos detecciones de la MISMA época:
            # serían dos fuentes distintas, no la misma vista dos veces.
            if any(o.epoch_index == obs.epoch_index for o in tracks[index].observations):
                continue
            separation = angular_separation_deg(ra, dec, track_ra, track_dec) * 3600.0
            if separation < best_separation:
                best_index, best_separation = index, separation

        if best_index >= 0 and best_separation <= match_radius_arcsec:
            tracks[best_index].observations.append(obs)
            positions = [(o.detection.position.ra_deg, o.detection.position.dec_deg) for o in tracks[best_index].observations]
            centroids[best_index] = (
                float(np.mean([p[0] for p in positions])),
                float(np.mean([p[1] for p in positions])),
            )
        else:
            tracks.append(SourceTrack(track_id="", observations=[obs]))
            centroids.append((ra, dec))

    numbered = tuple(
        SourceTrack(track_id=f"{observation_id}-TRK-{index:05d}", observations=track.observations)
        for index, track in enumerate(tracks)
    )
    return TrackingResult(tracks=numbered, n_epochs=n_epochs)
