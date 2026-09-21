"""Fotometría diferencial multiépoca de una estrella variable con hasta
`MAX_COMPARISON_STARS` estrellas de comparación reales, sobre N LIGHTS
del usuario.

No introduce ningún algoritmo fotométrico nuevo: reutiliza el registro
de fotogramas por patrón de estrellas (`astrometry.frame_registration`,
sin WCS ni red), la fotometría de apertura ya cerrada
(`photometry.aperture`) y el motor de variabilidad ya cerrado
(`temporal.variability`) -- esto es orquestación nueva sobre motores
científicos que ya existían y estaban probados, no un motor nuevo.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime

import numpy as np

from astrophysics_suite.astrometry.frame_registration import estimate_frame_translation, refine_position
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.detection.point_sources import detect_point_sources_in_array
from astrophysics_suite.imtools.ccd_noise import ccd_noise_adu
from astrophysics_suite.models.temporal import TemporalEvidence
from astrophysics_suite.photometry.aperture import aperture_photometry
from astrophysics_suite.tables.table import Table
from astrophysics_suite.temporal.variability import analyze_variability

ENGINE_NAME = "photometry.multi_frame_light_curve"
ENGINE_VERSION = "1.0"

MAX_COMPARISON_STARS = 5


@dataclass(frozen=True)
class FrameInput:
    """Un fotograma real ya cargado -- lo que este motor necesita de
    cada LIGHT del usuario, independiente de cómo se cargó."""

    label: str
    data: np.ndarray
    date_obs: datetime | None
    gain_e_per_adu: float | None = None
    read_noise_e: float = 0.0


@dataclass(frozen=True)
class FrameLightCurvePoint:
    """Una época real medida -- posiciones reajustadas, flujo medido de
    la variable y de cada comparación, y la magnitud diferencial (si se
    pudo calcular). Un fotograma sin medida válida lleva `skip_reason`
    explícito en vez de un valor inventado."""

    label: str
    date_obs: datetime | None
    hours_since_first: float | None
    translation_px: tuple[float, float]
    translation_inliers: int
    target_position: tuple[float, float]
    target_refined: bool
    target_net_flux: float | None
    target_snr: float | None
    comparison_positions: tuple[tuple[float, float], ...]
    comparison_refined: tuple[bool, ...]
    comparison_net_flux: tuple[float | None, ...]
    ensemble_net_flux: float | None
    diff_mag: float | None
    diff_mag_error: float | None
    skip_reason: str = ""


@dataclass(frozen=True)
class MultiFrameLightCurveResult:
    points: tuple[FrameLightCurvePoint, ...]
    temporal_evidence: TemporalEvidence
    table: Table
    provenance: Provenance

    @property
    def n_valid_epochs(self) -> int:
        return sum(1 for p in self.points if p.diff_mag is not None)


def _uncertainty_adu(data: np.ndarray, frame: FrameInput) -> np.ndarray:
    if frame.gain_e_per_adu is not None and frame.gain_e_per_adu > 0:
        return ccd_noise_adu(data, gain_e_per_adu=frame.gain_e_per_adu, read_noise_e=max(frame.read_noise_e, 0.0))
    return np.sqrt(np.clip(data, 1.0, None))


def _brightest_xy(data: np.ndarray, *, fwhm_px: float, threshold_sigma: float, max_stars: int) -> np.ndarray:
    sources = detect_point_sources_in_array(data, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma, max_sources=800)
    sources.sort(key=lambda s: -s[2])
    return np.array([[x, y] for x, y, _ in sources[:max_stars]])


def build_multi_frame_light_curve(
    frames: list[FrameInput],
    *,
    target_xy: tuple[float, float],
    comparison_xy: list[tuple[float, float]],
    detection_id: str,
    aperture_radius_px: float = 6.0,
    sky_r_in: float = 12.0,
    sky_r_out: float = 18.0,
    fwhm_px: float = 4.0,
    detection_threshold_sigma: float = 8.0,
    registration_tolerance_px: float = 3.0,
    refine_search_radius_px: float = 4.0,
    variability_min_epochs: int = 3,
    variability_sigma_threshold: float = 4.0,
    pipeline_version: str = "",
) -> MultiFrameLightCurveResult:
    """Fotometría diferencial real de `target_xy` frente al conjunto de
    `comparison_xy` (1 a `MAX_COMPARISON_STARS` estrellas, sumadas como
    flujo de referencia -- mismo criterio que un "ensemble" de
    comparación clásico) a través de `frames`, con el primero como
    referencia: las posiciones se dan en SU sistema de coordenadas de
    píxel.

    Cada fotograma posterior se registra contra el primero por
    coincidencia real de patrones de estrellas (sin WCS ni red -- ver
    `astrometry.frame_registration`), y cada posición se reajusta a la
    fuente real más cercana. Nunca inventa una posición ni un flujo: un
    fotograma sin traslación fiable, sin una fuente real cerca de una
    posición prevista, o sin fecha real de observación, se registra con
    su `skip_reason` explícito, y esa época no entra en el ajuste de
    variabilidad."""
    if not (1 <= len(comparison_xy) <= MAX_COMPARISON_STARS):
        raise ValueError(f"se requieren entre 1 y {MAX_COMPARISON_STARS} estrellas de comparación, se dieron {len(comparison_xy)}")
    if not frames:
        raise ValueError("se requiere al menos un fotograma")

    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    reference_xy = _brightest_xy(np.asarray(frames[0].data, dtype=float), fwhm_px=fwhm_px, threshold_sigma=detection_threshold_sigma, max_stars=60)

    t0: datetime | None = None
    points: list[FrameLightCurvePoint] = []
    for index, frame in enumerate(frames):
        data = np.asarray(frame.data, dtype=float)
        uncertainty = _uncertainty_adu(data, frame)

        if index == 0:
            dx, dy, inliers = 0.0, 0.0, len(reference_xy)
        else:
            target_field_xy = _brightest_xy(data, fwhm_px=fwhm_px, threshold_sigma=detection_threshold_sigma, max_stars=60)
            dx, dy, inliers = estimate_frame_translation(reference_xy, target_field_xy, tolerance_px=registration_tolerance_px)

        detected_this_frame = _brightest_xy(data, fwhm_px=fwhm_px, threshold_sigma=detection_threshold_sigma, max_stars=2000)

        def _place(xy: tuple[float, float]) -> tuple[float, float, bool]:
            return refine_position(detected_this_frame, xy[0] + dx, xy[1] + dy, search_radius_px=refine_search_radius_px)

        tx, ty, t_refined = _place(target_xy)
        comp_placed = [_place(xy) for xy in comparison_xy]
        comp_positions = tuple((x, y) for x, y, _ in comp_placed)
        comp_refined = tuple(r for _, _, r in comp_placed)

        target_measurement = aperture_photometry(
            data, uncertainty, tx, ty, radii=[aperture_radius_px], sky_r_in=sky_r_in, sky_r_out=sky_r_out, zeropoint_mag=0.0
        )[0]
        comp_measurements = [
            aperture_photometry(data, uncertainty, x, y, radii=[aperture_radius_px], sky_r_in=sky_r_in, sky_r_out=sky_r_out, zeropoint_mag=0.0)[0]
            for x, y in comp_positions
        ]

        comp_fluxes = tuple(m.net_flux for m in comp_measurements)
        valid_comp = [(m.net_flux, m.net_flux_uncertainty) for m in comp_measurements if m.net_flux is not None and m.net_flux > 0]
        ensemble_flux = sum(f for f, _ in valid_comp) if valid_comp else None
        ensemble_variance = sum(e**2 for _, e in valid_comp) if valid_comp else None

        hours = None
        if frame.date_obs is not None:
            if t0 is None:
                t0 = frame.date_obs
            hours = (frame.date_obs - t0).total_seconds() / 3600.0

        diff_mag, diff_mag_error, skip_reason = None, None, ""
        net_flux = target_measurement.net_flux
        if inliers < 2:
            skip_reason = f"registro poco fiable ({inliers} estrella(s) coincidente(s) con el fotograma de referencia)"
        elif not t_refined:
            skip_reason = "la estrella variable no se reajustó a ninguna fuente real cerca de la posición prevista"
        elif net_flux is None or net_flux <= 0:
            skip_reason = "flujo neto de la variable <= 0"
        elif not ensemble_flux or ensemble_flux <= 0:
            skip_reason = "ninguna estrella de comparación con flujo neto > 0"
        elif frame.date_obs is None:
            skip_reason = "sin fecha real de observación (DATE-OBS) en la cabecera"
        else:
            diff_mag = -2.5 * math.log10(net_flux / ensemble_flux)
            net_flux_error = target_measurement.net_flux_uncertainty or 0.0
            ensemble_error = math.sqrt(ensemble_variance) if ensemble_variance else 0.0
            relative_variance = 0.0
            if net_flux_error > 0:
                relative_variance += (net_flux_error / net_flux) ** 2
            if ensemble_error > 0:
                relative_variance += (ensemble_error / ensemble_flux) ** 2
            diff_mag_error = (2.5 / math.log(10.0)) * math.sqrt(relative_variance) if relative_variance > 0 else None

        points.append(
            FrameLightCurvePoint(
                label=frame.label, date_obs=frame.date_obs, hours_since_first=hours,
                translation_px=(dx, dy), translation_inliers=inliers,
                target_position=(tx, ty), target_refined=t_refined,
                target_net_flux=net_flux, target_snr=target_measurement.snr,
                comparison_positions=comp_positions, comparison_refined=comp_refined,
                comparison_net_flux=comp_fluxes, ensemble_net_flux=ensemble_flux,
                diff_mag=diff_mag, diff_mag_error=diff_mag_error, skip_reason=skip_reason,
            )
        )

    epochs = [{"time": p.hours_since_first, "value": p.diff_mag, "error": p.diff_mag_error} for p in points if p.diff_mag is not None]
    temporal_evidence = analyze_variability(
        epochs, detection_id=detection_id, min_epochs=variability_min_epochs,
        sigma_threshold=variability_sigma_threshold, pipeline_version=pipeline_version,
    )

    table = Table(
        columns=(
            "fotograma", "fecha_obs", "horas", "traslacion_px_x", "traslacion_px_y", "inliers_registro",
            "flujo_variable", "snr_variable", "flujo_ensemble", "mag_diferencial", "mag_diferencial_err", "motivo_descarte",
        ),
        units=("", "", "h", "px", "px", "", "ADU", "", "ADU", "mag", "mag", ""),
        rows=tuple(
            (
                p.label, p.date_obs.isoformat() if p.date_obs else "", p.hours_since_first,
                p.translation_px[0], p.translation_px[1], p.translation_inliers,
                p.target_net_flux, p.target_snr, p.ensemble_net_flux, p.diff_mag, p.diff_mag_error, p.skip_reason,
            )
            for p in points
        ),
    )

    return MultiFrameLightCurveResult(points=tuple(points), temporal_evidence=temporal_evidence, table=table, provenance=provenance)
