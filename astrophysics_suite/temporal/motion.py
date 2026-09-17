"""Motor de movimiento: de posiciones por época a movimiento propio real
-> `MotionEvidence`.

## La regla que evita el falso positivo más fácil de cometer

Una fuente cuya posición cambia entre épocas NO es necesariamente un
objeto en movimiento: puede ser error de registro, una PSF mal
centrada, o ruido de centroide. Por eso este motor:

1. Ajusta una trayectoria LINEAL por mínimos cuadrados a las posiciones
   con el tiempo real de cada época (no la diferencia entre la primera y
   la última: eso desperdicia las épocas intermedias y no da residuo).
2. Obtiene la incertidumbre del ajuste a partir del residuo real.
3. Solo declara `moving_source_candidate` cuando el movimiento supera su
   propia incertidumbre Y el residuo del ajuste es compatible con una
   trayectoria lineal -- un objeto real se mueve en línea recta en
   intervalos cortos; el ruido de registro no.

Con menos de 3 épocas se puede medir un desplazamiento pero NO su
residuo, así que no hay forma de distinguirlo de un error de registro:
el motor lo dice explícitamente en vez de declarar movimiento.
"""
from __future__ import annotations

import math

import numpy as np

from astrophysics_suite.core.enums import ValueKind

from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.discovery.source_tracks import SourceTrack
from astrophysics_suite.models.temporal import MotionEvidence

ENGINE_NAME = "temporal.motion"
ENGINE_VERSION = "1.0"

#: Significancia mínima para declarar movimiento: el desplazamiento debe
#: superar 5 veces su propia incertidumbre. Por debajo, es indistinguible
#: del ruido de centroide y del error de registro.
DEFAULT_MOTION_SIGMA = 5.0

#: Mínimo de épocas para poder medir el residuo del ajuste. Con 2 puntos
#: una recta pasa exactamente por ambos: el residuo es 0 por construcción
#: y no informa de nada.
MIN_EPOCHS_FOR_RESIDUAL = 3


def analyze_motion(
    track: SourceTrack,
    *,
    detection_id: str,
    registration_rms_arcsec: float | None = None,
    motion_sigma: float = DEFAULT_MOTION_SIGMA,
    pipeline_version: str = "",
) -> MotionEvidence:
    """Ajusta la trayectoria real de una fuente a lo largo de sus épocas.

    Devuelve siempre un `MotionEvidence`: cuando no se puede medir, con
    las magnitudes en NO DISPONIBLE y el motivo concreto, nunca con
    ceros que parezcan una medida."""
    # `MotionEvidence` no tiene todavía campo de procedencia (ver la fase de
    # provenance): mientras tanto, el método y las notas de cada `Quantity`
    # llevan el motor y las condiciones reales del ajuste, así que ningún
    # número sale de aquí sin poder decir de dónde viene.
    del pipeline_version
    positions = track.sky_positions()

    def unavailable(reason: str) -> MotionEvidence:
        return MotionEvidence.create(
            detection_id=detection_id,
            n_epochs_used=len(positions),
            pm_ra=Quantity.not_available(unit="arcsec/hour", method=ENGINE_NAME, reference=reason),
            pm_dec=Quantity.not_available(unit="arcsec/hour", method=ENGINE_NAME, reference=reason),
            pm_total=Quantity.not_available(unit="arcsec/hour", method=ENGINE_NAME, reference=reason),
            moving_source_candidate=False,
        )

    if len(positions) < 2:
        return unavailable(
            f"solo {len(positions)} época(s) con coordenadas celestes: hacen falta al menos 2 para medir desplazamiento"
        )
    if any(time is None for time, _, _ in positions):
        return unavailable(
            "alguna época no tiene fecha de observación (DATE-OBS): sin tiempo real no se puede convertir un "
            "desplazamiento en movimiento propio"
        )

    times = np.array([t.timestamp() for t, _, _ in positions], dtype=float)
    times_hours = (times - times[0]) / 3600.0
    span_hours = float(times_hours[-1] - times_hours[0])
    if span_hours <= 0:
        return unavailable("todas las épocas tienen la misma marca de tiempo: el intervalo es cero")

    ra = np.array([p[1] for p in positions], dtype=float)
    dec = np.array([p[2] for p in positions], dtype=float)
    mean_dec = float(np.mean(dec))
    # Desplazamientos en segundos de arco sobre el plano tangente local.
    x_arcsec = (ra - ra[0]) * math.cos(math.radians(mean_dec)) * 3600.0
    y_arcsec = (dec - dec[0]) * 3600.0

    design = np.vstack([times_hours, np.ones_like(times_hours)]).T
    slope_x, _ = np.linalg.lstsq(design, x_arcsec, rcond=None)[0]
    slope_y, _ = np.linalg.lstsq(design, y_arcsec, rcond=None)[0]
    residual_x = x_arcsec - (slope_x * times_hours + np.mean(x_arcsec - slope_x * times_hours))
    residual_y = y_arcsec - (slope_y * times_hours + np.mean(y_arcsec - slope_y * times_hours))
    rms_residual = float(np.sqrt(np.mean(residual_x**2 + residual_y**2)))

    n_epochs = len(positions)
    if n_epochs < MIN_EPOCHS_FOR_RESIDUAL:
        # Con 2 épocas hay desplazamiento medible pero no residuo: sin una
        # referencia externa de la calidad del registro, no se puede
        # separar movimiento real de error de registro.
        if registration_rms_arcsec is None or registration_rms_arcsec <= 0:
            return unavailable(
                f"{n_epochs} épocas: con menos de {MIN_EPOCHS_FOR_RESIDUAL} no hay residuo de ajuste, y sin un RMS de "
                f"registro conocido no se puede distinguir movimiento real de error de registro"
            )
        position_error = float(registration_rms_arcsec)
    else:
        # La incertidumbre del desplazamiento sale del residuo real del
        # ajuste, con los grados de libertad correctos.
        position_error = rms_residual * math.sqrt(n_epochs / max(n_epochs - 2, 1))
        if registration_rms_arcsec is not None and registration_rms_arcsec > 0:
            position_error = math.hypot(position_error, float(registration_rms_arcsec))

    slope_error = (position_error / span_hours) * math.sqrt(12.0 / max(n_epochs, 2)) if span_hours > 0 else float("inf")
    if not math.isfinite(slope_error):
        return unavailable("no se pudo estimar la incertidumbre del ajuste de trayectoria")

    pm_total_value = math.hypot(float(slope_x), float(slope_y))

    if slope_error <= 0.0:
        # Residuo exactamente cero: el ajuste lineal es perfecto. Eso NO
        # significa "no se mueve" -- una trayectoria recta perfecta es
        # justo lo que hace un asteroide real. Significa que la dispersión
        # no aporta ninguna incertidumbre, así que la significancia no se
        # puede establecer sin una estimación externa del error de posición
        # (RMS de registro o precisión de centroide).
        #
        # Se reporta el desplazamiento MEDIDO tal cual, sin barra de error
        # inventada, y `moving_source_candidate` queda en False porque no se
        # ha podido demostrar significancia -- no porque se haya demostrado
        # ausencia de movimiento. La diferencia está escrita en las notas.
        notes = (
            f"{n_epochs} épocas en {span_hours:.3f} h",
            "residuo del ajuste exactamente cero: la trayectoria es perfectamente lineal",
            f"desplazamiento medido {pm_total_value:.4f}\"/h, pero sin dispersión ni RMS de registro no se puede "
            f"asignar incertidumbre ni, por tanto, significancia",
            "no se declara movimiento por falta de significancia demostrable, NO por ausencia de desplazamiento",
        )
        return MotionEvidence.create(
            detection_id=detection_id,
            n_epochs_used=n_epochs,
            pm_ra=Quantity(value=float(slope_x), error=None, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                           method="linear_trajectory_fit", notes=notes),
            pm_dec=Quantity(value=float(slope_y), error=None, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                            method="linear_trajectory_fit", notes=notes),
            pm_total=Quantity(value=pm_total_value, error=None, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                              method="linear_trajectory_fit", notes=notes),
            moving_source_candidate=False,
        )

    significance = pm_total_value / slope_error
    is_moving = significance >= motion_sigma

    notes = (
        f"{n_epochs} épocas en {span_hours:.3f} h",
        f"residuo RMS del ajuste lineal: {rms_residual:.4f}\"",
        f"significancia: {significance:.2f}σ (umbral {motion_sigma:.1f}σ)",
    )
    return MotionEvidence.create(
        detection_id=detection_id,
        n_epochs_used=n_epochs,
        pm_ra=Quantity(value=float(slope_x), error=slope_error, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                       method="linear_trajectory_fit", notes=notes),
        pm_dec=Quantity(value=float(slope_y), error=slope_error, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                        method="linear_trajectory_fit", notes=notes),
        pm_total=Quantity(value=pm_total_value, error=slope_error, unit="arcsec/hour", kind=ValueKind.OBSERVED,
                          method="linear_trajectory_fit", notes=notes),
        moving_source_candidate=bool(is_moving),
    )
