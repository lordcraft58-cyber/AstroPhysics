"""Reducción de una sesión completa de LIGHTS -- el hueco principal que
señala el Mapa de capacidades IRAF (`docs/audit/13-IRAF-CAPABILITY-MAP.md`,
bloque `ccdred`): hasta esta fase, la GUI solo podía calibrar una imagen
científica activa a la vez, nunca una sesión real de observación con
varias exposiciones.

Esta orquestación aplica la misma cadena física fija de `calibrate_frame`
(bias -> dark escalado -> flat -> píxeles defectuosos), con overscan/
recorte y franjas opcionales, a cada LIGHT de una lista real -- y
opcionalmente combina el resultado con el mismo rechazo robusto de
`combine_images` que ya usan los fotogramas maestros. Un fotograma
maestro ya construido puede usarse aquí como producto derivado (vía
`master_bias`/`master_dark`/`master_flat`), pero esto nunca sustituye la
capacidad de reducir las LIGHTS originales -- los mismos píxeles crudos
hacen falta después para el análisis temporal y otros motores de
descubrimiento (instrucción explícita del encargo).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from astrophysics_suite.imtools.arithmetic import UncertainImage
from astrophysics_suite.reduction.calibration import CalibrationSteps, calibrate_frame
from astrophysics_suite.reduction.combine import CombineResult, combine_images
from astrophysics_suite.reduction.fringe import remove_fringe
from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.reduction.overscan import subtract_overscan


@dataclass(frozen=True)
class LightFrameReduction:
    source_path: str
    """Ruta de origen del LIGHT, solo para trazabilidad -- nunca releída."""
    calibrated: UncertainImage
    steps: CalibrationSteps
    overscan_level: np.ndarray | None = None
    fringe_scale_factor: float | None = None


@dataclass(frozen=True)
class ReductionSessionResult:
    frames: tuple[LightFrameReduction, ...]
    combined: CombineResult | None = None
    """Apilado final con rechazo de outliers, solo si se pidió `combine=True`."""


def reduce_light_frames(
    light_frames: list[np.ndarray],
    *,
    light_paths: list[str] | None = None,
    overscan_region: tuple[slice, slice] | None = None,
    trim_region: tuple[slice, slice] | None = None,
    overscan_function: str = "median",
    overscan_poly_degree: int = 3,
    gain_e_per_adu: float = 1.0,
    read_noise_e: float = 0.0,
    science_exposures_s: list[float] | None = None,
    master_bias: MasterFrame | None = None,
    master_dark: MasterFrame | None = None,
    master_flat: MasterFrame | None = None,
    bad_pixel_mask: np.ndarray | None = None,
    master_fringe: np.ndarray | None = None,
    fringe_fit_region: tuple[slice, slice] | None = None,
    combine: bool = False,
    combine_method: str = "median",
    combine_sigma_clip: float | None = 3.0,
    combine_max_iters: int = 5,
) -> ReductionSessionResult:
    """Reduce cada LIGHT de `light_frames` con la cadena física fija:
    overscan/recorte (si se pide) -> bias -> dark escalado por exposición
    -> flat -> píxeles defectuosos interpolados -> franjas (si se pide).
    Cualquier combinación de fotogramas maestros es válida, igual que en
    `calibrate_frame` -- no todas las sesiones necesitan las tres.

    Con `combine=True`, además apila los LIGHTS ya calibrados con rechazo
    robusto de outliers (`combine.combine_images`): el mismo mecanismo que
    los fotogramas maestros, aplicado ahora a ciencia real (p. ej. para
    obtener un producto combinado de mayor S/N a partir de varias
    exposiciones del mismo campo).

    `light_paths`, si se da, debe tener la misma longitud que
    `light_frames` y solo etiqueta cada `LightFrameReduction` para
    trazabilidad -- la capa de ciencia nunca toca el sistema de archivos.
    `science_exposures_s` permite un tiempo de exposición distinto por
    LIGHT (una sesión real puede variarlo entre tomas); si se omite y hay
    `master_dark`, `calibrate_frame` lanzará el mismo error que ya lanza
    para una sola imagen.
    """
    if not light_frames:
        raise ValueError("reduce_light_frames requiere al menos un LIGHT")
    if light_paths is not None and len(light_paths) != len(light_frames):
        raise ValueError("light_paths debe tener la misma longitud que light_frames")
    if science_exposures_s is not None and len(science_exposures_s) != len(light_frames):
        raise ValueError("science_exposures_s debe tener la misma longitud que light_frames")

    results: list[LightFrameReduction] = []
    for index, raw in enumerate(light_frames):
        path = light_paths[index] if light_paths is not None else ""
        exposure_s = science_exposures_s[index] if science_exposures_s is not None else None

        working = raw
        overscan_level = None
        if overscan_region is not None:
            overscan_result = subtract_overscan(
                working,
                overscan_region=overscan_region,
                trim_region=trim_region,
                function=overscan_function,
                poly_degree=overscan_poly_degree,
            )
            working = overscan_result.data
            overscan_level = overscan_result.overscan_level

        calibrated, steps = calibrate_frame(
            working,
            gain_e_per_adu=gain_e_per_adu,
            read_noise_e=read_noise_e,
            science_exposure_s=exposure_s,
            master_bias=master_bias,
            master_dark=master_dark,
            master_flat=master_flat,
            bad_pixel_mask=bad_pixel_mask,
        )

        fringe_scale = None
        if master_fringe is not None:
            fringe_result = remove_fringe(calibrated.data, master_fringe, fit_region=fringe_fit_region)
            calibrated = UncertainImage(
                data=fringe_result.data, uncertainty=calibrated.uncertainty, unit=calibrated.unit, mask=calibrated.mask
            )
            fringe_scale = fringe_result.scale_factor

        results.append(
            LightFrameReduction(
                source_path=path,
                calibrated=calibrated,
                steps=steps,
                overscan_level=overscan_level,
                fringe_scale_factor=fringe_scale,
            )
        )

    combined_result: CombineResult | None = None
    if combine:
        if len(results) < 2:
            raise ValueError("combine=True requiere al menos 2 LIGHTS calibrados para poder apilar")
        combined_result = combine_images(
            [frame.calibrated.data for frame in results],
            method=combine_method,
            sigma_clip=combine_sigma_clip,
            max_iters=combine_max_iters,
        )

    return ReductionSessionResult(frames=tuple(results), combined=combined_result)
