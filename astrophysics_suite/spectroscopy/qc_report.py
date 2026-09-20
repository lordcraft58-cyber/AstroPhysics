"""Informe de control de calidad unificado (§31): agrega en un solo
lugar diagnósticos que otros motores del proyecto ya calculaban por
separado (RMS de la traza espacial, RMS de la calibración en longitud
de onda, S/N mediana de la extracción, fracción de píxeles marcados) con
un semáforo OK/WARNING/ERROR por métrica.

Nunca calcula una magnitud nueva: cada valor de entrada lo produce
literalmente la misma función que ya lo calcula en cualquier otro
proceso del taller (`trace.trace_spectrum`, `trace.extract_sum`,
`wavelength.WavelengthSolution`, `frame2d.build_pixel_mask`,
`imtools.cosmic_rays.detect_cosmic_rays`) -- este módulo solo clasifica
esos números ya reales contra un umbral y los agrupa.

Los umbrales de OK/WARNING/ERROR son guías orientativas de
espectroscopía de aficionado/telescopio pequeño (documentadas
explícitamente en cada métrica vía `QCMetric.guideline`), nunca
presentadas como un estándar absoluto ni certificado -- mismo principio
de honestidad epistémica que el resto del proyecto.
"""
from __future__ import annotations

import math
from dataclasses import dataclass
from enum import Enum


class QCStatus(Enum):
    OK = "OK"
    WARNING = "WARNING"
    ERROR = "ERROR"
    NOT_AVAILABLE = "N/D"
    """La métrica no se pudo calcular con datos reales disponibles (p.
    ej. sin calibración en longitud de onda todavía) -- nunca se rellena
    con un valor inventado ni se cuenta como un fallo de calidad."""


@dataclass(frozen=True)
class QCMetric:
    name: str
    status: QCStatus
    value_text: str
    guideline: str
    """Explica el umbral usado en esta métrica -- honesto sobre que es
    una guía orientativa, no un estándar absoluto."""


@dataclass(frozen=True)
class QCReport:
    metrics: tuple[QCMetric, ...]

    @property
    def overall_status(self) -> QCStatus:
        """El peor estado real entre las métricas disponibles -- `N/D`
        solo si NINGUNA métrica pudo calcularse, nunca por defecto."""
        real_statuses = [m.status for m in self.metrics if m.status is not QCStatus.NOT_AVAILABLE]
        if not real_statuses:
            return QCStatus.NOT_AVAILABLE
        if QCStatus.ERROR in real_statuses:
            return QCStatus.ERROR
        if QCStatus.WARNING in real_statuses:
            return QCStatus.WARNING
        return QCStatus.OK


def _threshold_status(value: float, *, ok_max: float, warning_max: float) -> QCStatus:
    if value <= ok_max:
        return QCStatus.OK
    if value <= warning_max:
        return QCStatus.WARNING
    return QCStatus.ERROR


def trace_quality_metric(trace_rms_px: float, n_columns_used: int, n_columns_total: int) -> QCMetric:
    """A partir de `trace.TraceResult.rms_residual_px`/
    `n_columns_used_for_fit` reales (nunca recalculados aquí)."""
    status = _threshold_status(trace_rms_px, ok_max=0.5, warning_max=2.0)
    coverage = n_columns_used / n_columns_total if n_columns_total else 0.0
    if coverage < 0.5 and status is QCStatus.OK:
        # Poca evidencia real detrás del ajuste (ver TraceResult.
        # n_columns_used_for_fit): un RMS bajo apoyado en menos de la
        # mitad de las columnas puede no ser representativo -- nunca se
        # informa como bueno solo porque el número lo sea.
        status = QCStatus.WARNING
    return QCMetric(
        name="Traza espacial",
        status=status,
        value_text=f"RMS={trace_rms_px:.3f} px ({n_columns_used}/{n_columns_total} columnas con evidencia real)",
        guideline=(
            "Guía orientativa (no un estándar absoluto): RMS<0.5 px bueno, <2 px aceptable, por encima revisar "
            "la traza; se rebaja a WARNING si menos de la mitad de las columnas tuvo evidencia real."
        ),
    )


def wavelength_calibration_quality_metric(rms_residual_angstrom: float | None) -> QCMetric:
    """A partir de `wavelength.WavelengthSolution.rms_residual` real, o
    `None` si la imagen no tiene una calibración ajustada todavía."""
    if rms_residual_angstrom is None:
        return QCMetric(
            name="Calibración en longitud de onda", status=QCStatus.NOT_AVAILABLE, value_text="sin calibrar",
            guideline="Usa \"Calibrar longitud de onda...\" (menú Espectroscopía) antes de este informe para incluir esta métrica.",
        )
    status = _threshold_status(rms_residual_angstrom, ok_max=0.5, warning_max=2.0)
    return QCMetric(
        name="Calibración en longitud de onda", status=status, value_text=f"RMS={rms_residual_angstrom:.3f} Å",
        guideline=(
            "Guía orientativa para espectroscopía de resolución baja/media (no un estándar absoluto): "
            "RMS<0.5 Å bueno, <2 Å aceptable, por encima revisar el ajuste de líneas."
        ),
    )


def snr_metric(median_snr: float) -> QCMetric:
    """A partir de la S/N mediana real (flujo/incertidumbre real de la
    extracción, `NaN` donde no hay incertidumbre real que dividir)."""
    if not math.isfinite(median_snr):
        return QCMetric(
            name="Relación señal/ruido", status=QCStatus.NOT_AVAILABLE, value_text="N/D",
            guideline="Sin incertidumbre real positiva en ningún punto de la extracción con la que calcular una S/N real.",
        )
    if median_snr >= 20.0:
        status = QCStatus.OK
    elif median_snr >= 5.0:
        status = QCStatus.WARNING
    else:
        status = QCStatus.ERROR
    return QCMetric(
        name="Relación señal/ruido", status=status, value_text=f"S/N mediana={median_snr:.1f}",
        guideline=(
            "Guía orientativa (no un estándar absoluto): S/N>=20 buena, >=5 marginal (umbral de detección "
            "estándar en espectroscopía), por debajo de 5 poco fiable."
        ),
    )


def pixel_quality_metric(n_bad: int, n_total: int, *, saturate_available: bool) -> QCMetric:
    """A partir del recuento real de píxeles marcados por
    `frame2d.build_pixel_mask` (NONFINITE siempre; SATURATED solo si
    `saturate_available`; COSMIC_RAY si se pidió detectarlos) sobre TODO
    el fotograma -- misma fuente que `spectroscopy.quality_map`."""
    fraction = n_bad / n_total if n_total else 0.0
    status = _threshold_status(fraction, ok_max=0.001, warning_max=0.01)
    saturation_note = (
        "" if saturate_available
        else " -- SATURATE no está en la cabecera real: la detección de saturación queda inactiva, solo cuenta NaN/Inf y rayos cósmicos si se pidieron"
    )
    return QCMetric(
        name="Calidad de píxeles", status=status,
        value_text=f"{n_bad}/{n_total} píxel(es) marcado(s) ({fraction:.3%}){saturation_note}",
        guideline="Guía orientativa (no un estándar absoluto): <0.1% del fotograma bueno, <1% aceptable, por encima revisar el fotograma.",
    )
