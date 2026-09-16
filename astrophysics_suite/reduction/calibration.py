"""Aplicación de calibración de CCD -- equivalente propio de `ccdproc` de
IRAF: orquesta bias, dark (escalado por tiempo de exposición) y flat
sobre una imagen científica cruda, devolviendo un `UncertainImage` con
incertidumbre propagada de principio a fin (algo que el `ccdproc`
original nunca hacía).

Orden fijo, el mismo que documenta IRAF y el que exige la física del
problema -- invertirlo produce resultados sistemáticamente incorrectos:
(overscan ya aplicado por separado) -> bias -> dark -> flat.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

import numpy as np

from astrophysics_suite.imtools.arithmetic import UncertainImage
from astrophysics_suite.reduction.bad_pixel_mask import interpolate_bad_pixels
from astrophysics_suite.reduction.master_frames import MasterFrame


@dataclass(frozen=True)
class CalibrationSteps:
    """Qué pasos se aplicaron de verdad -- para que la procedencia (Fase
    4, `Provenance`) pueda declarar exactamente qué calibración recibió
    cada imagen, nunca de forma implícita."""

    bias_subtracted: bool = False
    dark_subtracted: bool = False
    dark_scale_factor: float | None = None
    flat_divided: bool = False
    bad_pixels_interpolated: bool = False


def calibrate_frame(
    raw: np.ndarray,
    *,
    gain_e_per_adu: float = 1.0,
    read_noise_e: float = 0.0,
    science_exposure_s: float | None = None,
    master_bias: MasterFrame | None = None,
    master_dark: MasterFrame | None = None,
    master_flat: MasterFrame | None = None,
    bad_pixel_mask: np.ndarray | None = None,
) -> tuple[UncertainImage, CalibrationSteps]:
    """Calibra una imagen científica cruda (ya corregida de overscan si
    procede, ver `overscan.py`) contra los fotogramas maestros dados.
    Cualquier combinación de `master_bias`/`master_dark`/`master_flat`
    es válida -- no todas las calibraciones necesitan las tres (p. ej.
    una cámara CMOS sin dark current significativo puede omitir el
    dark)."""
    image = UncertainImage.from_counts(
        raw, gain_e_per_adu=gain_e_per_adu, read_noise_e=read_noise_e, mask=bad_pixel_mask
    )
    steps = CalibrationSteps()

    if master_bias is not None:
        bias_image = UncertainImage(data=master_bias.data, uncertainty=master_bias.uncertainty, unit=image.unit)
        image = image - bias_image
        steps = replace(steps, bias_subtracted=True)

    dark_scale = None
    if master_dark is not None:
        if science_exposure_s is None:
            raise ValueError("science_exposure_s es obligatorio para escalar el dark maestro")
        if master_dark.exposure_s is None or master_dark.exposure_s <= 0:
            raise ValueError("master_dark.exposure_s debe estar definido y ser positivo")
        dark_scale = science_exposure_s / master_dark.exposure_s
        scaled_dark = UncertainImage(
            data=master_dark.data * dark_scale, uncertainty=master_dark.uncertainty * dark_scale, unit=image.unit
        )
        image = image - scaled_dark
        steps = replace(steps, dark_subtracted=True, dark_scale_factor=dark_scale)

    if master_flat is not None:
        flat_image = UncertainImage(data=master_flat.data, uncertainty=master_flat.uncertainty, unit="dimensionless")
        image = image / flat_image
        steps = replace(steps, flat_divided=True)

    if bad_pixel_mask is not None and np.any(bad_pixel_mask):
        interpolated_data = interpolate_bad_pixels(image.data, bad_pixel_mask)
        image = UncertainImage(data=interpolated_data, uncertainty=image.uncertainty, unit=image.unit, mask=bad_pixel_mask)
        steps = replace(steps, bad_pixels_interpolated=True)

    return image, steps
