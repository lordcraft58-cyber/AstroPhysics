"""Autoproceso de espectro (§34): encadena en un único paso los motores
YA existentes y probados de trazado, extracción, calibración en longitud
de onda por estrella de referencia (§13), identificación de líneas
(§10/§21) e informe de calidad (§31/§42) -- sin recalcular ninguna
física nueva, exactamente la misma disciplina de reutilización que ya
sigue `qc_report.py`.

Explícitamente FUERA de alcance de este módulo (§34, límites reales):

- bias/dark/flat: son correcciones de TODO el fotograma CCD, no
  específicas de espectroscopía -- se aplican antes, desde el menú
  "Reducción" (qt_app/reduction/), sobre cualquier tipo de imagen. Este
  autoproceso asume una imagen 2D YA reducida.
- calibración en longitud de onda por lámpara de arco: exige emparejar a
  mano cada línea detectada con su longitud de onda conocida
  (wavelength_fit_dialog.py) -- no se puede automatizar sin inventar ese
  emparejamiento. Este autoproceso usa en su lugar la calibración
  automática por estrella de referencia (§13, `reference_star_
  calibration.py`), y hereda su aviso obligatorio: PROVISIONAL, nunca al
  nivel de una lámpara real.
- calibración de flujo (sensfunc/`fluxcal.py`): necesita un espectro de
  una estrella ESTÁNDAR distinta, tomada aparte -- no es algo derivable
  de la imagen activa.

Cada etapa se registra en un `AutoprocessStep` propio con su estado real
(«ok» / «omitido» / «error») y el motivo -- un fallo en una etapa
OPCIONAL (calibración, identificación) nunca invalida ni oculta las
etapas obligatorias (traza, extracción) ya completadas antes; un fallo
en una etapa OBLIGATORIA (traza, extracción) se propaga como excepción,
igual que ya hacen `spectroscopy.trace`/`spectroscopy.qc_report` en el
explorador de procesos -- no hay nada real que informar sin ellas.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from astrophysics_suite.spectroscopy.calibration_provenance import WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.continuum import fit_continuum
from astrophysics_suite.spectroscopy.line_catalog import SpectralLine
from astrophysics_suite.spectroscopy.object_line_identification import ObjectLineMatch, identify_object_lines_in_spectrum
from astrophysics_suite.spectroscopy.qc_report import (
    QCReport,
    QCStatus,
    dispersion_metric,
    pixel_quality_metric,
    snr_metric,
    trace_quality_metric,
    wavelength_calibration_quality_metric,
    wavelength_range_metric,
)
from astrophysics_suite.spectroscopy.reference_star_calibration import calibrate_from_reference_star
from astrophysics_suite.spectroscopy.trace import ExtractedSpectrum, TraceResult, trace_spectrum
from astrophysics_suite.spectroscopy.wavelength import WavelengthSolution

_STATUS_OK = "ok"
_STATUS_SKIPPED = "omitido"
_STATUS_ERROR = "error"


@dataclass(frozen=True)
class AutoprocessStep:
    name: str
    status: str
    """«ok» / «omitido» / «error» -- nunca «ok» si el paso no se completó de verdad."""
    detail: str


@dataclass(frozen=True)
class AutoprocessResult:
    steps: tuple[AutoprocessStep, ...]
    trace: TraceResult
    spectrum: ExtractedSpectrum
    median_snr: float
    wavelength_solution: WavelengthSolution | None
    calibration_record: WavelengthCalibrationRecord | None
    line_matches: tuple[ObjectLineMatch, ...]
    qc_report: QCReport

    @property
    def overall_ok(self) -> bool:
        return all(step.status != _STATUS_ERROR for step in self.steps)


def run_autoprocess_spectrum(
    data: np.ndarray,
    uncertainty: np.ndarray,
    initial_center_px: float,
    *,
    quality_mask: np.ndarray,
    saturate_available: bool,
    extractor: Callable[..., ExtractedSpectrum],
    extraction_method_label: str,
    calibration_catalog: tuple[SpectralLine, ...],
    identify_catalog: tuple[SpectralLine, ...],
    mask: np.ndarray | None = None,
    fit_degree: int = 3,
    aperture_half_width: float = 4.0,
    sky_smooth_degree: int | None = None,
    sky_smooth_sigma_clip: float = 3.0,
    calibrate_wavelength: bool = True,
    reference_object: str = "(objeto sin nombre en la cabecera FITS)",
    approx_dispersion_angstrom_per_px: float = 1.4,
    approx_wavelength_at_pixel0: float = 3800.0,
    calibration_tolerance_angstrom: float = 15.0,
    calibration_degree: int = 1,
    identify_lines: bool = True,
    identify_tolerance_angstrom: float = 3.0,
) -> AutoprocessResult:
    """`extractor` ya resuelto (p. ej. `trace.extract_optimal`) en vez de
    un nombre de método -- este módulo de ciencia pura no conoce el
    diccionario de nombres en español de la GUI (`registry._EXTRACTION_
    METHODS`); `extraction_method_label` es solo para el texto del paso.

    Los umbrales secundarios de calibración/identificación no expuestos
    aquí (S/N mínima, separación mínima, rechazo del continuo...) usan
    los mismos valores por defecto que ya usan `spectroscopy.reference_
    star_calibration`/`spectroscopy.identify_lines` como procesos
    independientes -- quien necesite ajustarlos a mano sigue teniendo esos
    dos procesos dedicados.
    """
    steps: list[AutoprocessStep] = []

    trace = trace_spectrum(data, initial_center_px=initial_center_px, fit_degree=fit_degree, mask=mask)
    steps.append(AutoprocessStep(
        "Traza espacial", _STATUS_OK,
        f"centro inicial y={initial_center_px:.1f} px -> RMS={trace.rms_residual_px:.2f} px "
        f"({trace.n_columns_used_for_fit}/{len(trace.columns)} columnas con evidencia real).",
    ))

    spectrum = extractor(
        data, uncertainty, trace, mask=mask, aperture_half_width=aperture_half_width,
        sky_smooth_degree=sky_smooth_degree, sky_smooth_sigma_clip=sky_smooth_sigma_clip,
    )
    with np.errstate(divide="ignore", invalid="ignore"):
        snr_array = np.where(spectrum.flux_uncertainty > 0, spectrum.flux / spectrum.flux_uncertainty, np.nan)
    median_snr = float(np.nanmedian(snr_array)) if np.any(np.isfinite(snr_array)) else float("nan")
    sky_note = f", cielo suavizado (polinomio grado {sky_smooth_degree})" if sky_smooth_degree else ""
    steps.append(AutoprocessStep(
        "Extracción", _STATUS_OK,
        f"método={extraction_method_label}, S/N mediana={median_snr:.1f}, "
        f"{spectrum.n_columns_invalid} columna(s) sin medida real{sky_note}.",
    ))

    pixel = np.arange(spectrum.flux.size, dtype=np.float64)
    wavelength_solution: WavelengthSolution | None = None
    calibration_record: WavelengthCalibrationRecord | None = None
    if calibrate_wavelength:
        try:
            continuum_for_calibration = fit_continuum(pixel, spectrum.flux, degree=3, sigma_clip=2.5)
            calibration_record = calibrate_from_reference_star(
                pixel, spectrum.flux, continuum_for_calibration.continuum, calibration_catalog,
                approx_dispersion_angstrom_per_px=approx_dispersion_angstrom_per_px,
                approx_wavelength_at_pixel0=approx_wavelength_at_pixel0,
                tolerance_angstrom=calibration_tolerance_angstrom, reference_object=reference_object,
                degree=calibration_degree,
            )
        except ValueError as exc:
            steps.append(AutoprocessStep("Calibración en longitud de onda (§13, provisional)", _STATUS_ERROR, str(exc)))
        else:
            wavelength_solution = calibration_record.solution
            steps.append(AutoprocessStep(
                "Calibración en longitud de onda (§13, provisional)", _STATUS_OK,
                f"grado {calibration_record.solution.degree}, {calibration_record.n_lines_used} línea(s) real(es), "
                f"RMS={calibration_record.solution.rms_residual:.4f} Å.",
            ))
    else:
        steps.append(AutoprocessStep("Calibración en longitud de onda (§13, provisional)", _STATUS_SKIPPED, "desactivada por el usuario."))

    line_matches: tuple[ObjectLineMatch, ...] = ()
    if identify_lines:
        if wavelength_solution is None:
            steps.append(AutoprocessStep(
                "Identificación de líneas", _STATUS_SKIPPED,
                "necesita una calibración en longitud de onda real -- el paso anterior no se completó.",
            ))
        else:
            wavelength = np.asarray(wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)
            continuum_for_identification = fit_continuum(wavelength, spectrum.flux, degree=3, sigma_clip=2.5)
            line_matches = identify_object_lines_in_spectrum(
                wavelength, spectrum.flux, continuum_for_identification.continuum, identify_catalog,
                tolerance_angstrom=identify_tolerance_angstrom,
            )
            steps.append(AutoprocessStep(
                "Identificación de líneas", _STATUS_OK,
                f"{len(line_matches)} línea(s) sugerida(s) (SUGERENCIAS únicamente -- revisar antes de aceptar).",
            ))
    else:
        steps.append(AutoprocessStep("Identificación de líneas", _STATUS_SKIPPED, "desactivada por el usuario."))

    pixel_min, pixel_max = 0.0, float(data.shape[1] - 1)
    n_bad = int(np.count_nonzero(quality_mask))
    report = QCReport(metrics=(
        trace_quality_metric(trace.rms_residual_px, trace.n_columns_used_for_fit, len(trace.columns)),
        wavelength_calibration_quality_metric(wavelength_solution.rms_residual if wavelength_solution is not None else None),
        wavelength_range_metric(wavelength_solution, pixel_min, pixel_max),
        dispersion_metric(wavelength_solution, (pixel_min + pixel_max) / 2.0),
        snr_metric(median_snr),
        pixel_quality_metric(n_bad, quality_mask.size, saturate_available=saturate_available),
    ))
    steps.append(AutoprocessStep(
        "Informe de calidad (§31/§42)",
        _STATUS_ERROR if report.overall_status is QCStatus.ERROR else _STATUS_OK,
        f"estado global: {report.overall_status.value}.",
    ))

    return AutoprocessResult(
        steps=tuple(steps), trace=trace, spectrum=spectrum, median_snr=median_snr,
        wavelength_solution=wavelength_solution, calibration_record=calibration_record,
        line_matches=line_matches, qc_report=report,
    )
