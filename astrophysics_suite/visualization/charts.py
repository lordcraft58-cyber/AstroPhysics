"""Gráficas reales a partir de `reporting.models.DataSeries`/`ScientificResult`
-- cada función dibuja EXACTAMENTE los puntos que trae la serie, nunca
recalcula ni suaviza nada. Backend `Agg` (sin pantalla) para poder
ejecutarse igual desde la GUI, desde exportación en lote o desde pruebas.
"""
from __future__ import annotations

import io

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt  # noqa: E402

from astrophysics_suite.models.anomaly import AnomalyVector  # noqa: E402
from astrophysics_suite.reporting.models import DataSeries  # noqa: E402

_FIGSIZE = (6.0, 3.6)
_DPI = 110


def render_series(series: DataSeries, *, title: str = "") -> bytes:
    """Dibuja UNA `DataSeries` real y devuelve un PNG real (bytes) --
    sin escribir a disco: el llamador decide si la guarda, la embebe en
    HTML (base64) o la muestra en la GUI (`QPixmap.loadFromData`)."""
    fig, ax = plt.subplots(figsize=_FIGSIZE, dpi=_DPI)
    try:
        _draw_series(ax, series)
        if title:
            ax.set_title(title, fontsize=10)
        fig.tight_layout()
        buffer = io.BytesIO()
        fig.savefig(buffer, format="png")
        return buffer.getvalue()
    finally:
        plt.close(fig)


def _draw_series(ax, series: DataSeries) -> None:
    x_label = f"{series.x_label} [{series.x_unit}]" if series.x_unit else series.x_label
    y_label = f"{series.y_label} [{series.y_unit}]" if series.y_unit else series.y_label

    if series.kind == "bar":
        positions = list(series.x)
        ax.bar(positions, series.y, color="#4c78a8")
        if series.x_categories:
            ax.set_xticks(positions)
            ax.set_xticklabels(series.x_categories, rotation=30, ha="right", fontsize=8)
    elif series.kind == "scatter":
        ax.scatter(series.x, series.y, color="#4c78a8", s=28)
        ax.plot(series.x, series.y, color="#4c78a8", alpha=0.35, linewidth=1)
        if series.x and series.y:
            ax.scatter([series.x[0]], [series.y[0]], color="#54a24b", s=48, zorder=3, label="primera época")
            ax.scatter([series.x[-1]], [series.y[-1]], color="#e45756", s=48, zorder=3, label="última época")
            ax.legend(fontsize=7, loc="best")
    elif series.kind == "residual":
        outliers = set(series.outlier_indices or ())
        inliers_x = [x for i, x in enumerate(series.x) if i not in outliers]
        inliers_y = [y for i, y in enumerate(series.y) if i not in outliers]
        ax.axhline(0.0, color="#888888", linewidth=1, linestyle="--")
        ax.scatter(inliers_x, inliers_y, color="#4c78a8", s=28, label="punto usado")
        if outliers:
            outlier_x = [series.x[i] for i in sorted(outliers)]
            outlier_y = [series.y[i] for i in sorted(outliers)]
            ax.scatter(outlier_x, outlier_y, color="#e45756", s=48, marker="x", zorder=3, label="atípico (>3σ MAD)")
            ax.legend(fontsize=7, loc="best")
    else:
        if series.y_error is not None:
            ax.errorbar(series.x, series.y, yerr=series.y_error, fmt="o-", color="#4c78a8", markersize=4, linewidth=1, capsize=2)
        else:
            ax.plot(series.x, series.y, "o-", color="#4c78a8", markersize=4, linewidth=1)

    ax.set_xlabel(x_label, fontsize=9)
    ax.set_ylabel(y_label, fontsize=9)
    ax.tick_params(labelsize=8)
    ax.grid(True, alpha=0.25)


def render_anomaly_vector(vector: AnomalyVector) -> bytes | None:
    """Atajo directo sobre un `AnomalyVector` real -- reconstruye la
    misma `DataSeries` de barras que arma `reporting.candidate_report`
    (evita que la GUI tenga que pasar por `ScientificResult` completo
    solo para ver esta gráfica). `None` si ninguna dimensión tiene
    evidencia real -- nunca una gráfica vacía disfrazada de resultado."""
    from astrophysics_suite.reporting.candidate_report import ANOMALY_DIMENSIONS, ANOMALY_LABELS

    available = [(name, getattr(vector, name)) for name in ANOMALY_DIMENSIONS if (q := getattr(vector, name)) is not None and q.is_available]
    if not available:
        return None
    series = DataSeries(
        name="Vector de anomalía", x=tuple(range(len(available))), y=tuple(q.value for _n, q in available),
        x_label="Dimensión", y_label="Significancia", y_unit="sigma", kind="bar",
        x_categories=tuple(ANOMALY_LABELS[n] for n, _q in available),
    )
    return render_series(series, title="Vector de anomalía")
