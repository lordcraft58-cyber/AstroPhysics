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

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.imtools.arithmetic import UncertainImage
from astrophysics_suite.reduction.calibration import CalibrationSteps, calibrate_frame
from astrophysics_suite.reduction.combine import CombineResult, combine_images
from astrophysics_suite.reduction.fringe import remove_fringe
from astrophysics_suite.reduction.illumination import IlluminationMap, apply_illumination_correction
from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.reduction.overscan import subtract_overscan
from astrophysics_suite.reduction.provenance import ReductionRecord, build_reduction_provenance
from astrophysics_suite.reduction.sky import SkyBackgroundFit, fit_sky_background, subtract_sky_background


@dataclass(frozen=True)
class LightFrameReduction:
    source_path: str
    """Ruta de origen del LIGHT, solo para trazabilidad -- nunca releída."""
    calibrated: UncertainImage
    steps: CalibrationSteps
    overscan_level: np.ndarray | None = None
    fringe_scale_factor: float | None = None
    sky_background: SkyBackgroundFit | None = None
    record: ReductionRecord | None = None
    """Qué se le hizo de verdad a este LIGHT, reunido en un solo sitio --
    lo que se escribe después en la cabecera del archivo calibrado."""
    provenance: Provenance | None = None
    """Procedencia real (Fase 4). `CalibrationSteps` existía desde su
    primera versión declarando que servía para esto; hasta ahora nadie
    llegaba a construirla."""


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
    illumination_map: IlluminationMap | None = None,
    subtract_sky: bool = False,
    sky_degree: int = 2,
    sky_sigma_clip: float = 3.0,
    combine: bool = False,
    combine_method: str = "median",
    combine_sigma_clip: float | None = 3.0,
    combine_max_iters: int = 5,
    pipeline_version: str = "",
) -> ReductionSessionResult:
    """Reduce cada LIGHT de `light_frames` con la cadena física fija:
    overscan/recorte (si se pide) -> bias -> dark escalado por exposición
    -> flat -> píxeles defectuosos interpolados -> corrección de
    iluminación (si se pide) -> franjas (si se pide) -> corrección de
    cielo (si se pide). Cualquier combinación de fotogramas maestros es
    válida, igual que en `calibrate_frame` -- no todas las sesiones
    necesitan las tres.

    `illumination_map`, si se da (ver `illumination.build_illumination_map`,
    normalmente derivado del mismo flat maestro), corrige el patrón de
    iluminación a gran escala que un flat de cúpula no siempre reproduce.
    `subtract_sky=True` ajusta y resta, por LIGHT, una superficie de
    fondo de cielo de grado `sky_degree` con rechazo de fuentes
    (`sky.fit_sky_background`) -- a diferencia de la iluminación, este
    gradiente varía de una toma a otra (luna, contaminación lumínica), así
    que se recalcula para cada LIGHT en vez de derivarse de un maestro.

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

        if illumination_map is not None:
            illuminated_data = apply_illumination_correction(calibrated.data, illumination_map)
            calibrated = UncertainImage(data=illuminated_data, uncertainty=calibrated.uncertainty, unit=calibrated.unit, mask=calibrated.mask)

        fringe_scale = None
        if master_fringe is not None:
            fringe_result = remove_fringe(calibrated.data, master_fringe, fit_region=fringe_fit_region)
            calibrated = UncertainImage(
                data=fringe_result.data, uncertainty=calibrated.uncertainty, unit=calibrated.unit, mask=calibrated.mask
            )
            fringe_scale = fringe_result.scale_factor

        sky_fit = None
        if subtract_sky:
            sky_fit = fit_sky_background(calibrated.data, degree=sky_degree, sigma_clip=sky_sigma_clip)
            sky_subtracted_data = subtract_sky_background(calibrated.data, sky_fit)
            calibrated = UncertainImage(
                data=sky_subtracted_data, uncertainty=calibrated.uncertainty, unit=calibrated.unit, mask=calibrated.mask
            )

        record = ReductionRecord(
            steps=steps,
            overscan_corrected=overscan_region is not None,
            trimmed=trim_region is not None,
            illumination_corrected=illumination_map is not None,
            fringe_removed=master_fringe is not None,
            fringe_scale_factor=fringe_scale,
            sky_subtracted=subtract_sky,
            sky_degree=sky_degree if subtract_sky else None,
            gain_e_per_adu=gain_e_per_adu,
            read_noise_e=read_noise_e,
        )
        results.append(
            LightFrameReduction(
                source_path=path,
                calibrated=calibrated,
                steps=steps,
                overscan_level=overscan_level,
                fringe_scale_factor=fringe_scale,
                sky_background=sky_fit,
                record=record,
                provenance=build_reduction_provenance(record, pipeline_version=pipeline_version),
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
