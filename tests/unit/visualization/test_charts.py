"""`render_series`/`render_anomaly_vector` contra series REALES (no
simplemente "no lanza excepción"): cada gráfica debe ser un PNG real,
no trivial, y `render_anomaly_vector` nunca debe fabricar una gráfica
para un vector sin evidencia real."""
from __future__ import annotations

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.anomaly import AnomalyVector
from astrophysics_suite.reporting.models import DataSeries
from astrophysics_suite.visualization.charts import render_anomaly_vector, render_series

_PNG_MAGIC = b"\x89PNG\r\n\x1a\n"


def _assert_real_png(data: bytes) -> None:
    assert isinstance(data, (bytes, bytearray))
    assert data[:8] == _PNG_MAGIC
    assert len(data) > 2000


def test_render_series_line_with_error_bars_produces_a_real_png():
    series = DataSeries(
        name="Curva de luz", x=(0.0, 1.3, 2.6, 3.9), y=(1000.0, 1017.0, 1028.0, 1038.0),
        x_label="Tiempo relativo", y_label="Brillo instrumental", x_unit="h", y_unit="ADU",
        y_error=(8.0, 8.0, 8.0, 8.0), kind="line",
    )
    png = render_series(series, title="Curva de luz")
    _assert_real_png(png)


def test_render_series_scatter_produces_a_real_png():
    series = DataSeries(
        name="Trayectoria", x=(10.6847, 10.6852, 10.6857), y=(41.2687, 41.2689, 41.2691),
        x_label="RA", y_label="Dec", x_unit="deg", y_unit="deg", kind="scatter",
    )
    png = render_series(series, title="Trayectoria")
    _assert_real_png(png)


def test_render_series_residual_with_outliers_produces_a_real_png():
    series = DataSeries(
        name="Residuales del ajuste WCS", x=(0.0, 1.0, 2.0, 3.0), y=(0.1, -0.15, 0.08, 1.9),
        x_label="Índice", y_label="Residual", y_unit="arcsec", kind="residual", outlier_indices=(3,),
    )
    png = render_series(series, title="Residuales del ajuste WCS")
    _assert_real_png(png)


def test_render_series_residual_without_outliers_produces_a_real_png():
    series = DataSeries(
        name="Residuales del punto cero", x=(0.0, 1.0, 2.0), y=(0.02, -0.01, 0.015),
        x_label="Índice", y_label="Residual", y_unit="mag", kind="residual",
    )
    png = render_series(series, title="Residuales del punto cero")
    _assert_real_png(png)


def test_render_series_bar_with_categories_produces_a_real_png():
    series = DataSeries(
        name="Vector de anomalía", x=(0.0, 1.0), y=(5.2, 6.8),
        x_label="Dimensión", y_label="Significancia", y_unit="sigma", kind="bar",
        x_categories=("Fotométrica", "Temporal"),
    )
    png = render_series(series, title="Vector de anomalía")
    _assert_real_png(png)


def test_render_series_line_in_magnitudes_inverts_the_y_axis():
    # Convención astronómica real: magnitud menor = más brillo. Una curva
    # de luz en magnitudes (p. ej. Estrellas Variables -> Curva de luz
    # multiépoca) debe verse con el eje invertido, o una estrella que se
    # apaga parece "subir" en la gráfica.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from astrophysics_suite.visualization.charts import _draw_series

    series_mag = DataSeries(
        name="Curva de luz", x=(0.0, 1.0, 2.0), y=(12.0, 12.5, 13.0),
        x_label="t", y_label="Magnitud diferencial", y_unit="mag", kind="line",
    )
    fig, ax = plt.subplots()
    _draw_series(ax, series_mag)
    assert ax.yaxis_inverted()
    plt.close(fig)


def test_render_series_line_in_adu_does_not_invert_the_y_axis():
    # La curva de luz en ADU de pico que ya usa el informe de
    # Descubrimiento (informe 81) no debe cambiar: más ADU ya significa
    # más brillo, sin necesitar invertir nada.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from astrophysics_suite.visualization.charts import _draw_series

    series_adu = DataSeries(
        name="Curva de luz", x=(0.0, 1.0, 2.0), y=(1000.0, 1050.0, 1100.0),
        x_label="t", y_label="Brillo instrumental", y_unit="ADU (pico)", kind="line",
    )
    fig, ax = plt.subplots()
    _draw_series(ax, series_adu)
    assert not ax.yaxis_inverted()
    plt.close(fig)


def test_render_series_residual_in_magnitudes_does_not_invert_the_y_axis():
    # Un residual en magnitudes (p. ej. el ajuste de punto cero) es una
    # desviación alrededor de cero, no una medida de brillo -- invertirlo
    # no tiene el mismo sentido que en una curva de luz, y este
    # comportamiento ya existía antes de la corrección de la curva de
    # luz multiépoca: se fija aquí para que no cambie por accidente.
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from astrophysics_suite.visualization.charts import _draw_series

    series_residual = DataSeries(
        name="Residuales del punto cero", x=(0.0, 1.0, 2.0), y=(0.02, -0.01, 0.015),
        x_label="Índice", y_label="Residual", y_unit="mag", kind="residual",
    )
    fig, ax = plt.subplots()
    _draw_series(ax, series_residual)
    assert not ax.yaxis_inverted()
    plt.close(fig)


def test_render_series_two_different_series_produce_different_images():
    a = DataSeries(name="a", x=(0.0, 1.0), y=(1.0, 2.0), x_label="t", y_label="v", kind="line")
    b = DataSeries(name="b", x=(0.0, 1.0), y=(10.0, 20.0), x_label="t", y_label="v", kind="line")
    assert render_series(a) != render_series(b)


def test_render_anomaly_vector_with_real_evidence_produces_a_real_png():
    vector = AnomalyVector.create(
        detection_id="DET-TEST",
        photometric=Quantity(value=5.2, error=0.4, unit="sigma", kind=ValueKind.PROXY, method="flux_zscore"),
        temporal=Quantity(value=6.8, error=0.5, unit="sigma", kind=ValueKind.PROXY, method="slope_significance"),
    )
    png = render_anomaly_vector(vector)
    assert png is not None
    _assert_real_png(png)


def test_render_anomaly_vector_without_any_available_dimension_returns_none():
    vector = AnomalyVector.create(detection_id="DET-EMPTY")
    assert render_anomaly_vector(vector) is None


def test_render_anomaly_vector_with_all_dimensions_not_available_returns_none():
    vector = AnomalyVector.create(
        detection_id="DET-ALL-NA",
        photometric=Quantity.not_available(unit="sigma", method="flux_zscore"),
        astrometric=Quantity.not_available(unit="sigma", method="wcs_residual_zscore"),
    )
    assert render_anomaly_vector(vector) is None
