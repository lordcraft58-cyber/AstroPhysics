"""Preprocesado espectroscópico 2D (§7): orquesta bias -> dark -> flat
-> píxeles defectuosos -> limpieza de rayos cósmicos, en ese orden fijo,
sobre motores YA probados -- no reimplementa ninguno de los cinco pasos:

- bias/dark/flat/bad-pixel: `reduction.calibration.calibrate_frame`
  (el mismo motor que ya usa `reduction/session_pipeline.py`).
- rayos cósmicos: `imtools.cosmic_rays.detect_cosmic_rays`
  (L.A.Cosmic real, ya usado en reducción de imágenes de campo amplio,
  cableado aquí explícitamente para espectroscopía por primera vez).

El resultado es un `frame2d.SpectralFrame2D` con máscara de calidad
combinada -- listo para pasar directamente a `trace.trace_spectrum`/
`extract_sum`/`extract_optimal` vía su parámetro `mask`.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.imtools.cosmic_rays import detect_cosmic_rays
from astrophysics_suite.reduction.calibration import CalibrationSteps, calibrate_frame
from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.spectroscopy.frame2d import SpectralFrame2D, build_pixel_mask


@dataclass(frozen=True)
class SpectroscopicPreprocessingResult:
    frame: SpectralFrame2D
    calibration_steps: CalibrationSteps
    n_cosmic_rays_flagged: int
    """0 si `detect_cosmic_rays_enabled=False` -- nunca un número
    inventado cuando el paso no se ejecutó."""
    cosmic_ray_interpolation_applied: bool


def preprocess_spectroscopic_frame(
    raw: np.ndarray,
    *,
    gain_e_per_adu: float = 1.0,
    read_noise_e: float = 0.0,
    science_exposure_s: float | None = None,
    master_bias: MasterFrame | None = None,
    master_dark: MasterFrame | None = None,
    master_flat: MasterFrame | None = None,
    bad_pixel_mask: np.ndarray | None = None,
    saturate_adu: float | None = None,
    detect_cosmic_rays_enabled: bool = True,
    cosmic_ray_sigclip: float = 4.5,
    cosmic_ray_objlim: float = 5.0,
    apply_cosmic_ray_interpolation: bool = False,
) -> SpectroscopicPreprocessingResult:
    """RAW -> BIAS -> DARK -> FLAT -> BAD PIXEL MASK -> COSMIC RAY
    CLEANING -> 2D SCIENCE (§7), con cualquier combinación de
    fotogramas maestros (no todas las sesiones necesitan las tres,
    igual que `reduction.calibration.calibrate_frame`).

    `apply_cosmic_ray_interpolation=False` (por defecto): los píxeles
    de rayo cósmico se MARCAN en la máscara de calidad, pero sus
    valores originales se conservan tal cual -- `trace`/`extract` ya
    saben excluir píxeles marcados sin necesidad de tocar el dato
    (§6: "interpolación opcional únicamente sobre píxeles marcados").
    Con `True`, se sustituyen por la reconstrucción de
    `detect_cosmic_rays` (mediana local), y la máscara los sigue
    marcando igualmente -- interpolar no es lo mismo que dejar de saber
    que ese píxel era sospechoso.
    """
    calibrated, steps = calibrate_frame(
        raw, gain_e_per_adu=gain_e_per_adu, read_noise_e=read_noise_e,
        science_exposure_s=science_exposure_s, master_bias=master_bias,
        master_dark=master_dark, master_flat=master_flat, bad_pixel_mask=bad_pixel_mask,
    )

    cosmic_ray_mask = None
    n_cosmic_rays = 0
    data = calibrated.data
    if detect_cosmic_rays_enabled:
        cr_result = detect_cosmic_rays(
            data, gain_e_per_adu=gain_e_per_adu, read_noise_e=read_noise_e,
            sigclip=cosmic_ray_sigclip, objlim=cosmic_ray_objlim, satlevel=saturate_adu,
        )
        cosmic_ray_mask = cr_result.mask
        n_cosmic_rays = cr_result.n_pixels_flagged
        if apply_cosmic_ray_interpolation:
            data = cr_result.cleaned_data

    quality_mask = build_pixel_mask(
        data, saturate_adu=saturate_adu, dead_pixel_mask=calibrated.mask, cosmic_ray_mask=cosmic_ray_mask,
    )
    frame = SpectralFrame2D(data=data, variance=calibrated.uncertainty**2, mask=quality_mask)

    return SpectroscopicPreprocessingResult(
        frame=frame, calibration_steps=steps, n_cosmic_rays_flagged=n_cosmic_rays,
        cosmic_ray_interpolation_applied=bool(detect_cosmic_rays_enabled and apply_cosmic_ray_interpolation),
    )
