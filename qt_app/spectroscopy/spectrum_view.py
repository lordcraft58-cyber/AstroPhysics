"""Visor de espectros 1D real -- reemplaza la "tira 1D repetida como
imagen 2D" que usaban `spectroscopy.continuum`/`trace`/`line`/
`multiaperture` desde la Fase 9.5 (limitación documentada explícitamente
en cada uno de esos cierres) por un widget dedicado: ejes con unidades
reales, zoom a rueda de ratón y arrastre para desplazar (mismo lenguaje
de interacción que `ImageView`), doble clic para restablecer la vista, y
lectura en vivo bajo el cursor -- mismo "readout" que ya tiene
`ImageView` para píxeles, mostrado en la barra de estado por
`main_window.py`. Ningún proceso científico cambia: esto es una capa de
presentación pura (`QPainter` directo, sin `QGraphicsView`/escena --
un trazo de línea no necesita manipular ítems, solo redibujarse) sobre
los mismos arrays que los cuatro procesos ya producían.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QMouseEvent, QPainter, QPainterPath, QPen, QWheelEvent
from PySide6.QtWidgets import QComboBox, QWidget

from qt_app.spectroscopy.spectrum_plot_data import (
    WAVELENGTH_UNITS,
    SpectrumMarker,
    SpectrumPlotData,
    SpectrumSeries,
    convert_wavelength_plot_data,
)
from qt_app.theme import DARK

_MARGIN_LEFT = 68.0
_MARGIN_BOTTOM = 42.0
_MARGIN_TOP = 18.0
_MARGIN_TOP_WITH_UNIT_SELECTOR = 44.0
"""Margen superior mayor cuando hay selector de unidades real (§15) --
deja sitio real al combo sin que se solape con la leyenda, que también
se dibuja pegada a la esquina superior del área de la gráfica."""
_MARGIN_RIGHT = 18.0
_MIN_RANGE = 1e-9
_N_TICKS = 5
_ZOOM_IN_FACTOR = 0.8
_ZOOM_OUT_FACTOR = 1.25


def _format_tick(value: float, span: float) -> str:
    if not np.isfinite(span) or span <= 0:
        return f"{value:.3g}"
    if span >= 1000:
        return f"{value:.0f}"
    if span >= 10:
        return f"{value:.1f}"
    if span >= 0.1:
        return f"{value:.3f}"
    return f"{value:.3g}"


class SpectrumView(QWidget):
    value_hovered = Signal(float, float)
    """`(x, y)` bajo el cursor en unidades de datos reales (posición
    continua, interpolada) -- `nan` si el cursor cae fuera del área de
    la gráfica."""
    point_hovered = Signal(float, float, float, str, str)
    """`(x, y, y_error, x_label, y_label)` del punto REAL más cercano de
    la primera serie con datos finitos bajo el cursor -- nunca un valor
    interpolado entre dos puntos reales (§29: el tooltip debe mostrar
    píxel/λ, flujo, error y S/N reales, no una lectura continua sin
    sentido físico entre dos medidas). `y_error` es `NaN` si esa serie no
    lleva incertidumbre real (`SpectrumSeries.y_error is None`). Todos
    `NaN` si el cursor cae fuera del área de la gráfica o ninguna serie
    tiene datos finitos."""
    point_right_clicked = Signal(float, float, QPointF)
    """`(x_real, y_real, global_pos)` del punto REAL más cercano al clic
    derecho (nunca una posición interpolada, mismo criterio que
    `point_hovered`) -- identificación manual de líneas (§10): el
    llamador decide qué candidatas de catálogo mostrar y si añadir una
    marca real (`add_marker`), este widget solo informa del punto real
    señalado. No se emite si el clic cae fuera del área de la gráfica."""

    def __init__(self, plot_data: SpectrumPlotData, title: str, parent=None):
        super().__init__(parent)
        self.title = title
        self._data = plot_data
        self.setMouseTracking(True)
        self.setMinimumSize(320, 240)
        self._x_range, self._y_range = self._full_data_range()
        self._panning = False
        self._pan_last_pixel: QPointF | None = None

        self.unit_combo: QComboBox | None = None
        """Selector de unidades real (Å/nm/μm, §15) -- solo existe cuando
        `plot_data.x_unit` declara una longitud de onda real ya
        calibrada; para un eje de píxel sin calibrar no hay ninguna
        unidad física que ofrecer, así que el combo ni se construye."""
        if plot_data.x_unit:
            self.unit_combo = QComboBox(self)
            self.unit_combo.addItems(WAVELENGTH_UNITS)
            self.unit_combo.setCurrentText(plot_data.x_unit)
            self.unit_combo.currentTextChanged.connect(self._on_unit_changed)
            self._position_unit_combo()

    def _on_unit_changed(self, unit: str) -> None:
        self.set_plot_data(convert_wavelength_plot_data(self._data, unit))

    def _position_unit_combo(self) -> None:
        if self.unit_combo is None:
            return
        self.unit_combo.adjustSize()
        self.unit_combo.move(int(_MARGIN_LEFT), 4)

    def resizeEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        self._position_unit_combo()
        super().resizeEvent(event)

    # ---------------------------------------------------------------- rango de datos
    def _full_data_range(self) -> tuple[tuple[float, float], tuple[float, float]]:
        if self._data.series:
            all_x = np.concatenate([s.x for s in self._data.series])
            all_y = np.concatenate([s.y for s in self._data.series])
        else:
            all_x = all_y = np.array([])
        finite_x = all_x[np.isfinite(all_x)]
        finite_y = all_y[np.isfinite(all_y)]
        x_lo, x_hi = (float(np.min(finite_x)), float(np.max(finite_x))) if finite_x.size else (0.0, 1.0)
        y_lo, y_hi = (float(np.min(finite_y)), float(np.max(finite_y))) if finite_y.size else (0.0, 1.0)
        if x_hi <= x_lo:
            x_lo, x_hi = x_lo - 0.5, x_lo + 0.5
        if y_hi <= y_lo:
            y_lo, y_hi = y_lo - 0.5, y_lo + 0.5
        x_pad = max((x_hi - x_lo) * 0.02, _MIN_RANGE)
        y_pad = max((y_hi - y_lo) * 0.08, _MIN_RANGE)
        return (x_lo - x_pad, x_hi + x_pad), (y_lo - y_pad, y_hi + y_pad)

    def reset_view(self) -> None:
        self._x_range, self._y_range = self._full_data_range()
        self.update()

    def set_plot_data(self, plot_data: SpectrumPlotData) -> None:
        """Sustituye los datos graficados (p. ej. tras convertir de
        unidad, §15) y restablece la vista al rango completo de los
        datos nuevos -- el zoom/paneo previo ya no tiene sentido en la
        unidad nueva."""
        self._data = plot_data
        self.reset_view()

    @property
    def x_unit(self) -> str:
        """Unidad real del eje X activo ahora mismo (`""` si es un eje de
        píxel sin calibrar) -- para que el llamador de `point_right_
        clicked` sepa en qué unidad viene `x_real` antes de buscar en un
        catálogo (siempre en Å, §10/§15)."""
        return self._data.x_unit

    def add_marker(self, marker: SpectrumMarker) -> None:
        """Añade una marca real (p. ej. una identificación de línea
        aceptada por el usuario, §10) sin resetear el zoom/paneo actual
        -- a diferencia de `set_plot_data`, que sí lo hace porque cambia
        los propios datos."""
        self._data = SpectrumPlotData(
            series=self._data.series, x_label=self._data.x_label, y_label=self._data.y_label,
            markers=self._data.markers + (marker,), x_unit=self._data.x_unit,
        )
        self.update()

    # ---------------------------------------------------------------- mapeo dato <-> píxel
    def _plot_rect(self) -> QRectF:
        top_margin = _MARGIN_TOP_WITH_UNIT_SELECTOR if self.unit_combo is not None else _MARGIN_TOP
        return QRectF(
            _MARGIN_LEFT, top_margin,
            max(1.0, self.width() - _MARGIN_LEFT - _MARGIN_RIGHT),
            max(1.0, self.height() - top_margin - _MARGIN_BOTTOM),
        )

    def _data_to_pixel(self, x: float, y: float) -> QPointF:
        rect = self._plot_rect()
        x_lo, x_hi = self._x_range
        y_lo, y_hi = self._y_range
        px = rect.left() + (x - x_lo) / (x_hi - x_lo) * rect.width()
        py = rect.bottom() - (y - y_lo) / (y_hi - y_lo) * rect.height()
        return QPointF(px, py)

    def _pixel_to_data(self, px: float, py: float) -> tuple[float, float]:
        rect = self._plot_rect()
        x_lo, x_hi = self._x_range
        y_lo, y_hi = self._y_range
        x = x_lo + (px - rect.left()) / rect.width() * (x_hi - x_lo)
        y = y_lo + (rect.bottom() - py) / rect.height() * (y_hi - y_lo)
        return x, y

    # ---------------------------------------------------------------- dibujo
    def paintEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        painter.fillRect(self.rect(), QColor(DARK.bg_input))
        rect = self._plot_rect()
        painter.fillRect(rect, QColor(DARK.bg))

        self._draw_grid(painter, rect)
        for marker in self._data.markers:
            self._draw_marker(painter, rect, marker)
        for series in self._data.series:
            self._draw_series(painter, rect, series)
        painter.setPen(QPen(QColor(DARK.border_strong), 1))
        painter.drawRect(rect)
        self._draw_axis_titles(painter, rect)
        self._draw_legend(painter, rect)
        painter.end()

    def _draw_grid(self, painter: QPainter, rect: QRectF) -> None:
        grid_pen = QPen(QColor(DARK.border), 1, Qt.PenStyle.DotLine)
        text_pen = QPen(QColor(DARK.ink_muted))
        x_lo, x_hi = self._x_range
        y_lo, y_hi = self._y_range

        for i in range(1, _N_TICKS):
            frac = i / _N_TICKS
            x_value = x_lo + frac * (x_hi - x_lo)
            px = rect.left() + frac * rect.width()
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(px, rect.top()), QPointF(px, rect.bottom()))
            painter.setPen(text_pen)
            painter.drawText(QRectF(px - 40, rect.bottom() + 4, 80, 18), Qt.AlignmentFlag.AlignHCenter, _format_tick(x_value, x_hi - x_lo))

            y_value = y_lo + frac * (y_hi - y_lo)
            py = rect.bottom() - frac * rect.height()
            painter.setPen(grid_pen)
            painter.drawLine(QPointF(rect.left(), py), QPointF(rect.right(), py))
            painter.setPen(text_pen)
            painter.drawText(QRectF(0, py - 8, _MARGIN_LEFT - 8, 16), Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter, _format_tick(y_value, y_hi - y_lo))

    def _draw_marker(self, painter: QPainter, rect: QRectF, marker: SpectrumMarker) -> None:
        x0 = self._data_to_pixel(marker.x_start, 0.0).x()
        x1 = self._data_to_pixel(marker.x_end, 0.0).x()
        left, right = sorted((x0, x1))
        left, right = max(left, rect.left()), min(right, rect.right())
        if right <= left:
            return
        color = QColor(marker.color)
        color.setAlpha(40)
        painter.fillRect(QRectF(left, rect.top(), right - left, rect.height()), color)
        if marker.label:
            painter.setPen(QPen(QColor(marker.color)))
            # la banda puede ser más estrecha que el texto -- se centra
            # sobre su punto medio con el ancho real del texto (medido
            # por fuente), nunca recortado al ancho de la propia banda.
            label_width = painter.fontMetrics().horizontalAdvance(marker.label) + 8.0
            center_x = (left + right) / 2.0
            painter.drawText(QRectF(center_x - label_width / 2.0, rect.top() + 2, label_width, 16), Qt.AlignmentFlag.AlignHCenter, marker.label)

    def _draw_series(self, painter: QPainter, rect: QRectF, series: SpectrumSeries) -> None:
        painter.setClipRect(rect)
        color = QColor(series.color)
        if series.style == "points":
            painter.setPen(QPen(color, 1))
            painter.setBrush(color)
            for x, y in zip(series.x, series.y):
                if np.isfinite(x) and np.isfinite(y):
                    point = self._data_to_pixel(float(x), float(y))
                    painter.drawEllipse(point, 2.0, 2.0)
        else:
            pen = QPen(color, 1.6)
            if series.style == "dashed":
                pen.setStyle(Qt.PenStyle.DashLine)
            painter.setPen(pen)
            painter.drawPath(self._build_path(series))
        painter.setClipping(False)

    def _build_path(self, series: SpectrumSeries) -> QPainterPath:
        path = QPainterPath()
        started = False
        for x, y in zip(series.x, series.y):
            if not (np.isfinite(x) and np.isfinite(y)):
                started = False
                continue
            point = self._data_to_pixel(float(x), float(y))
            if not started:
                path.moveTo(point)
                started = True
            else:
                path.lineTo(point)
        return path

    def _draw_axis_titles(self, painter: QPainter, rect: QRectF) -> None:
        painter.setPen(QPen(QColor(DARK.ink)))
        painter.drawText(QRectF(rect.left(), rect.bottom() + 20, rect.width(), 18), Qt.AlignmentFlag.AlignHCenter, self._data.x_label)

        painter.save()
        painter.translate(14, rect.center().y())
        painter.rotate(-90)
        painter.drawText(QRectF(-rect.height() / 2, -9, rect.height(), 18), Qt.AlignmentFlag.AlignHCenter, self._data.y_label)
        painter.restore()

    def _draw_legend(self, painter: QPainter, rect: QRectF) -> None:
        labeled = [s for s in self._data.series if s.label]
        if len(labeled) < 2:
            return
        swatch, gap, padding = 14.0, 6.0, 8.0
        row_height = 16.0
        # ancho real por fuente, nunca un ancho fijo que recorte una
        # etiqueta larga (p. ej. "Continuo ajustado").
        text_width = max(painter.fontMetrics().horizontalAdvance(s.label) for s in labeled)
        text_left = rect.right() - padding - text_width
        line_right = text_left - gap
        line_left = line_right - swatch
        top = rect.top() + 6
        for series in labeled:
            painter.setPen(QPen(QColor(series.color), 2))
            painter.drawLine(QPointF(line_left, top + row_height / 2), QPointF(line_right, top + row_height / 2))
            painter.setPen(QPen(QColor(DARK.ink)))
            painter.drawText(QRectF(text_left, top, text_width, row_height), Qt.AlignmentFlag.AlignLeft, series.label)
            top += row_height

    # ---------------------------------------------------------------- lectura en vivo
    def _nearest_real_point(self, x_query: float) -> tuple[float, float, float] | None:
        """`(x_real, y_real, y_error_real)` del punto real más cercano a
        `x_query` en la primera serie con algún dato finito -- `y_error_real`
        es `NaN` si esa serie no lleva incertidumbre real. `None` si
        ninguna serie tiene ningún punto finito."""
        for series in self._data.series:
            finite = np.isfinite(series.x) & np.isfinite(series.y)
            if not np.any(finite):
                continue
            xs, ys = series.x[finite], series.y[finite]
            idx = int(np.argmin(np.abs(xs - x_query)))
            y_error = float("nan")
            if series.y_error is not None:
                errors = np.asarray(series.y_error)[finite]
                y_error = float(errors[idx])
            return float(xs[idx]), float(ys[idx]), y_error
        return None

    # ---------------------------------------------------------------- interacción
    def wheelEvent(self, event: QWheelEvent) -> None:  # noqa: N802 -- override de Qt
        factor = _ZOOM_IN_FACTOR if event.angleDelta().y() > 0 else _ZOOM_OUT_FACTOR
        pos = event.position()
        cx, cy = self._pixel_to_data(pos.x(), pos.y())
        x_lo, x_hi = self._x_range
        y_lo, y_hi = self._y_range
        self._x_range = (cx - (cx - x_lo) * factor, cx + (x_hi - cx) * factor)
        self._y_range = (cy - (cy - y_lo) * factor, cy + (y_hi - cy) * factor)
        self.update()

    def mousePressEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = True
            self._pan_last_pixel = event.position()
            self.setCursor(Qt.CursorShape.ClosedHandCursor)
        elif event.button() == Qt.MouseButton.RightButton:
            pos = event.position()
            if self._plot_rect().contains(pos):
                x, _y = self._pixel_to_data(pos.x(), pos.y())
                nearest = self._nearest_real_point(x)
                if nearest is not None:
                    x_real, y_real, _y_error = nearest
                    self.point_right_clicked.emit(x_real, y_real, event.globalPosition())
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        pos = event.position()
        x, y = self._pixel_to_data(pos.x(), pos.y())
        inside = self._plot_rect().contains(pos)
        self.value_hovered.emit(x if inside else float("nan"), y if inside else float("nan"))

        nearest = self._nearest_real_point(x) if inside else None
        if nearest is not None:
            self.point_hovered.emit(*nearest, self._data.x_label, self._data.y_label)
        else:
            self.point_hovered.emit(float("nan"), float("nan"), float("nan"), self._data.x_label, self._data.y_label)

        if self._panning and self._pan_last_pixel is not None:
            rect = self._plot_rect()
            delta = pos - self._pan_last_pixel
            x_lo, x_hi = self._x_range
            y_lo, y_hi = self._y_range
            dx = -delta.x() * (x_hi - x_lo) / rect.width()
            dy = delta.y() * (y_hi - y_lo) / rect.height()
            self._x_range = (x_lo + dx, x_hi + dx)
            self._y_range = (y_lo + dy, y_hi + dy)
            self._pan_last_pixel = pos
            self.update()
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        if event.button() == Qt.MouseButton.LeftButton:
            self._panning = False
            self._pan_last_pixel = None
            self.unsetCursor()
        super().mouseReleaseEvent(event)

    def mouseDoubleClickEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        self.reset_view()
        super().mouseDoubleClickEvent(event)
