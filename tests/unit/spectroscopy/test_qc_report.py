"""`qc_report.py`: clasifica OK/WARNING/ERROR números REALES ya
calculados por otros motores -- nunca calcula una magnitud nueva
(§31, §42)."""
from __future__ import annotations

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
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution


def test_trace_quality_metric_is_ok_for_a_tight_real_fit():
    metric = trace_quality_metric(0.1, 190, 200)
    assert metric.status is QCStatus.OK
    assert "0.1" in metric.value_text or "0.100" in metric.value_text


def test_trace_quality_metric_degrades_with_high_rms():
    assert trace_quality_metric(1.0, 190, 200).status is QCStatus.WARNING
    assert trace_quality_metric(5.0, 190, 200).status is QCStatus.ERROR


def test_trace_quality_metric_warns_on_low_coverage_even_with_a_low_rms():
    # RMS bajo pero apoyado en menos de la mitad de las columnas reales:
    # no se informa como bueno solo porque el número lo sea.
    metric = trace_quality_metric(0.1, 50, 200)
    assert metric.status is QCStatus.WARNING


def test_wavelength_calibration_quality_metric_is_not_available_without_a_real_solution():
    metric = wavelength_calibration_quality_metric(None)
    assert metric.status is QCStatus.NOT_AVAILABLE


def test_wavelength_calibration_quality_metric_thresholds():
    assert wavelength_calibration_quality_metric(0.1).status is QCStatus.OK
    assert wavelength_calibration_quality_metric(1.0).status is QCStatus.WARNING
    assert wavelength_calibration_quality_metric(5.0).status is QCStatus.ERROR


def test_snr_metric_is_not_available_for_a_nonfinite_value():
    metric = snr_metric(float("nan"))
    assert metric.status is QCStatus.NOT_AVAILABLE


def test_snr_metric_thresholds():
    assert snr_metric(50.0).status is QCStatus.OK
    assert snr_metric(10.0).status is QCStatus.WARNING
    assert snr_metric(2.0).status is QCStatus.ERROR


def test_pixel_quality_metric_thresholds_and_saturation_note():
    good = pixel_quality_metric(1, 1_000_000, saturate_available=True)
    assert good.status is QCStatus.OK
    assert "SATURATE" not in good.value_text

    warning = pixel_quality_metric(5_000, 1_000_000, saturate_available=True)
    assert warning.status is QCStatus.WARNING

    error = pixel_quality_metric(50_000, 1_000_000, saturate_available=True)
    assert error.status is QCStatus.ERROR

    without_saturate = pixel_quality_metric(1, 1_000_000, saturate_available=False)
    assert "SATURATE" in without_saturate.value_text


def test_wavelength_range_metric_is_not_available_without_a_real_solution():
    metric = wavelength_range_metric(None, 0.0, 149.0)
    assert metric.status is QCStatus.NOT_AVAILABLE


def test_wavelength_range_metric_reports_the_real_range_at_both_trace_ends():
    solution = fit_wavelength_solution([0.0, 149.0], [4000.0, 4300.0], degree=1)
    metric = wavelength_range_metric(solution, 0.0, 149.0)
    assert metric.status is QCStatus.OK
    assert metric.value_text == "4000.0 - 4300.0 Å"


def test_wavelength_range_metric_orders_low_to_high_regardless_of_solution_direction():
    # una dispersión negativa (longitud de onda decreciente con el píxel) real:
    # el rango sigue reportándose de menor a mayor, nunca invertido.
    solution = fit_wavelength_solution([0.0, 149.0], [4300.0, 4000.0], degree=1)
    metric = wavelength_range_metric(solution, 0.0, 149.0)
    assert metric.value_text == "4000.0 - 4300.0 Å"


def test_dispersion_metric_is_not_available_without_a_real_solution():
    metric = dispersion_metric(None, 75.0)
    assert metric.status is QCStatus.NOT_AVAILABLE


def test_dispersion_metric_recovers_a_known_linear_dispersion():
    solution = fit_wavelength_solution([0.0, 149.0], [4000.0, 4300.0], degree=1)
    metric = dispersion_metric(solution, 75.0)
    assert metric.status is QCStatus.OK
    expected = 300.0 / 149.0
    assert metric.value_text == f"{expected:.4f} Å/px"


def test_qc_report_overall_status_is_the_worst_real_status():
    report = QCReport(metrics=(
        trace_quality_metric(0.1, 190, 200),
        wavelength_calibration_quality_metric(None),
        snr_metric(50.0),
        pixel_quality_metric(1, 1_000_000, saturate_available=True),
    ))
    assert report.overall_status is QCStatus.OK  # el N/D no cuenta como fallo

    degraded = QCReport(metrics=(
        trace_quality_metric(0.1, 190, 200),
        wavelength_calibration_quality_metric(5.0),  # ERROR
        snr_metric(10.0),  # WARNING
        pixel_quality_metric(1, 1_000_000, saturate_available=True),
    ))
    assert degraded.overall_status is QCStatus.ERROR


def test_qc_report_overall_status_is_not_available_when_nothing_could_be_computed():
    report = QCReport(metrics=(
        wavelength_calibration_quality_metric(None),
        snr_metric(float("nan")),
    ))
    assert report.overall_status is QCStatus.NOT_AVAILABLE


def test_all_metrics_document_their_guideline_as_orientative_not_absolute():
    metrics = (
        trace_quality_metric(0.1, 190, 200),
        wavelength_calibration_quality_metric(0.1),
        snr_metric(50.0),
        pixel_quality_metric(1, 1_000_000, saturate_available=True),
    )
    for metric in metrics:
        assert "orientativa" in metric.guideline
