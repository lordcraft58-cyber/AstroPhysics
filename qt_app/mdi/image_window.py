"""Ventana de imagen dentro del área MDI -- muestra el array científico
a través del STF (nunca lo modifica), con zoom dinámico vía rueda del
ratón, tal como pide el encargo ("lupa/zoom dinámico"), y un modo de
selección de posiciones a clic para los procesos que lo necesitan
(fotometría de PSF, trazado espectral).
"""
from __future__ import annotations

from dataclasses import replace

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QMouseEvent, QPainterPath, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from astrophysics_suite.spectroscopy.trace import SkyWindow, TraceResult
from qt_app.mdi.stf import STFParams, compute_stf_params, stf_to_uint8
from qt_app.spectroscopy.trace_overlay_data import TraceOverlay

_PROCESS_MIME_TYPE = "application/x-astrophysics-process-id"
_MARKER_COLOR = QColor("#f0b429")
_MARKER_RADIUS = 5.0
_TRACE_OVERLAY_PALETTE = ("#4a9edb", "#4fc9b0", "#d9a441", "#d9707a", "#8f8fe0")
"""Mismos colores que `qt_app.theme.DARK` -- sin importar `theme.py`
directamente aquí, para no acoplar el visor genérico de imagen (usable
también fuera de espectroscopía) a esa decisión de paleta."""
_SKY_OVERLAY_COLOR = "#58a6ff"
_CALIBRATION_OVERLAY_COLOR = "#c77dff"
"""Color distinto de OBJETO (`_TRACE_OVERLAY_PALETTE`) y CIELO
(`_SKY_OVERLAY_COLOR`) para el canal de calibración lateral/simultánea
(§14) -- las tres regiones deben distinguirse a simple vista."""
_APERTURE_EDGE_HIT_TOLERANCE_PX = 3.0
"""Distancia real, en píxeles de DATOS (no de pantalla -- igual que el
propio overlay, independiente del zoom), dentro de la cual un clic
sobre el borde de la apertura cuenta como "agarrarlo" para arrastrar
(§2)."""
_MIN_APERTURE_HALF_WIDTH_PX = 0.5
"""Nunca se deja arrastrar la apertura a un semiancho que colapse la
ventana de extracción a (casi) cero píxeles reales."""


class ImageView(QGraphicsView):
    process_dropped = Signal(str)
    """Se emite cuando se suelta un icono de proceso sobre esta vista --
    el arrastrar-y-soltar sobre una imagen que pide el encargo."""

    picking_finished = Signal(list)
    """Se emite al terminar una sesión de selección de posiciones, con la
    lista de puntos `(x_px, y_px)` marcados (posiblemente vacía si se
    canceló sin marcar ninguno)."""

    pixel_hovered = Signal(float, float, float)
    """Se emite al mover el ratón sobre la imagen, con `(x_px, y_px,
    valor_adu)` bajo el cursor -- el "readout" de lectura de píxel al
    estilo PixInsight, mostrado en la barra de estado por
    `main_window.py`. `valor_adu` es `nan` si el cursor cae fuera de la
    imagen."""

    aperture_edited = Signal(float)
    """Se emite al soltar el ratón tras arrastrar el borde de la
    apertura sobre el overlay de traza (§2), con el nuevo semiancho real
    en píxeles -- `main_window.py` lo usa para recalcular la extracción
    real con `trace_edit_context` sin retrazar ni pedir un nuevo clic."""

    def __init__(self, data: np.ndarray, title: str, parent=None, *, wcs=None, header: dict | None = None, source_path: str | None = None):
        super().__init__(parent)
        self.data = data
        self.title = title
        self.wcs = wcs
        """El WCS real cargado del FITS (`astropy.wcs.WCS`, o `None` si el
        archivo no tenía uno) -- disponible para cualquier proceso que
        necesite coordenadas celestes reales (p. ej. calibración
        fotométrica contra un catálogo), inyectado por `main_window`."""
        self.header = header
        """Header real del FITS de origen (`dict`, o `None` si la imagen
        no viene de un archivo -- p. ej. un resultado intermedio de un
        proceso) -- usado por "Resolver placa automáticamente..." para
        estimar RA/Dec/escala aproximadas (`FOCALLEN`, `XPIXSZ`, `RA`/
        `DEC` u `OBJCTRA`/`OBJCTDEC`) antes de pedírselas al usuario."""
        self.source_path = source_path
        """Ruta del FITS de origen en disco, o `None` -- usada para
        proponer un nombre de archivo real al guardar una copia con el
        WCS resuelto."""
        self.fitted_wcs_solution = None
        """`astrophysics_suite.astrometry.wcs_fit.WCSSolution` ajustado a
        mano sobre esta ventana (ver "Ajustar WCS..."), distinto de
        `self.wcs` (que viene de la cabecera del FITS, si la tenía) --
        `None` hasta que el usuario ajuste uno."""
        self.fitted_wavelength_solution = None
        """`astrophysics_suite.spectroscopy.wavelength.WavelengthSolution`
        ajustada sobre esta ventana (ver "Calibrar longitud de onda...")
        -- `None` hasta que el usuario ajuste una."""
        self.wavelength_calibration_record = None
        """`astrophysics_suite.spectroscopy.calibration_provenance.
        WavelengthCalibrationRecord` -- la misma solución que
        `fitted_wavelength_solution` MÁS de dónde salió (lámpara real,
        etc.), para poder guardar el espectro calibrado con procedencia
        real (`CALTYPE`) en vez de solo la solución matemática. `None`
        hasta que se ajuste una calibración."""
        self.wavelength_calibration_spectrum = None
        """El espectro 1D real (ADU) sobre el que se detectaron las
        líneas de arco para `fitted_wavelength_solution` -- el mismo
        array que "Guardar espectro calibrado..." escribe a FITS, para
        no volver a suponer qué fila es el espectro."""
        self.processing_history: list = []
        """Cadena real de `astrophysics_suite.spectroscopy.processing_
        history.ProcessingHistoryEntry` -- una por cada proceso que se
        aplicó sobre ESTA ventana, en el orden real en que se ejecutó
        (§36/§39), rellenada por `main_window._on_process_finished`.
        Nunca se reordena ni se recorta: es la trazabilidad completa que
        "Guardar espectro calibrado..." escribe junto al producto."""
        self.stf_params: STFParams = compute_stf_params(data)
        self.stf_enabled = True

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(self.renderHints())
        self.setAcceptDrops(True)
        self.setMouseTracking(True)

        self._display_buffer: np.ndarray | None = None
        self.refresh_display()

        self._picking = False
        self._picking_max: int | None = None
        self._picked_points: list[tuple[float, float]] = []
        self._picked_markers: list[QGraphicsEllipseItem] = []
        self._drag_mode_before_picking = self.dragMode()

        self._trace_overlay_items: list[QGraphicsItem] = []
        """Traza/apertura/cielo dibujados sobre la imagen real por
        `set_trace_overlay` -- vacío mientras no se haya trazado/extraído
        nada todavía en esta ventana (§2/§3/§5/§28 del encargo)."""
        self.trace_edit_context = None
        """`qt_app.spectroscopy.trace_overlay_data.TraceEditContext` real
        de la última traza/extracción de UNA sola apertura en esta
        ventana (no multi-apertura/objeto extendido, que trazan varios
        objetos a la vez) -- permite recalcular la extracción real tras
        arrastrar el borde de la apertura (§2). `None` mientras no haya
        ninguna traza editable todavía."""
        self.trace_overlay_locked = False
        """Si es `True`, arrastrar el borde de la apertura queda
        desactivado -- protección real contra un arrastre accidental
        (§2), activable/desactivable desde el menú Vista."""
        self._trace_overlay_single: TraceOverlay | None = None
        """El único `TraceOverlay` dibujado actualmente -- `None` sin
        overlay, o con varios overlays simultáneos (multi-apertura),
        que no son editables por arrastre en este slice."""
        self._dragging_aperture = False
        self._live_aperture_half_width: float | None = None

    def refresh_display(self) -> None:
        if self.stf_enabled:
            buffer_8bit = stf_to_uint8(self.data, self.stf_params)
        else:
            span = float(np.ptp(self.data)) or 1.0
            normalized = (self.data - float(np.min(self.data))) / span
            buffer_8bit = np.clip(normalized * 255.0, 0, 255).astype(np.uint8)

        # QImage no copia el buffer por defecto -- se guarda la referencia
        # para que no la recoja el recolector de basura mientras Qt sigue
        # usándola, y además se fuerza una copia interna con `.copy()`
        # para no depender de ese ciclo de vida en absoluto.
        self._display_buffer = np.ascontiguousarray(buffer_8bit)
        height, width = self._display_buffer.shape
        image = QImage(self._display_buffer.data, width, height, width, QImage.Format.Format_Grayscale8).copy()
        self._pixmap_item.setPixmap(QPixmap.fromImage(image))
        self._scene.setSceneRect(0, 0, width, height)

    def set_stf_enabled(self, enabled: bool) -> None:
        self.stf_enabled = enabled
        self.refresh_display()

    def recompute_stf(self) -> None:
        self.stf_params = compute_stf_params(self.data)
        self.refresh_display()

    def wheelEvent(self, event: QWheelEvent) -> None:
        factor = 1.25 if event.angleDelta().y() > 0 else 0.8
        self.scale(factor, factor)

    # ---------------------------------------------------------------- selección de posiciones
    def start_picking(self, *, max_points: int | None = None) -> None:
        """Entra en modo selección: clic izquierdo marca una posición
        (en coordenadas de píxel de la imagen, no de pantalla); clic
        derecho termina la selección. Si `max_points` se da, termina
        automáticamente al alcanzarlo (p. ej. `max_points=1` para un
        único centro de traza)."""
        self._picking = True
        self._picking_max = max_points
        self._picked_points = []
        self._clear_markers()
        self._drag_mode_before_picking = self.dragMode()
        self.setDragMode(QGraphicsView.DragMode.NoDrag)
        self.setCursor(Qt.CursorShape.CrossCursor)

    def finish_picking(self) -> None:
        if not self._picking:
            return
        self._picking = False
        self.setDragMode(self._drag_mode_before_picking)
        self.unsetCursor()
        points = list(self._picked_points)
        self._clear_markers()
        self._picked_points = []
        self.picking_finished.emit(points)

    def _clear_markers(self) -> None:
        for marker in self._picked_markers:
            self._scene.removeItem(marker)
        self._picked_markers.clear()

    # ---------------------------------------------------------------- overlay de traza/apertura/cielo
    def set_trace_overlay(self, overlays) -> None:
        """Dibuja la traza real, los límites reales de apertura (línea
        continua/discontinua) y las regiones reales de cielo (línea
        discontinua azul) sobre la imagen -- `overlays` es un
        `qt_app.spectroscopy.trace_overlay_data.TraceOverlay` o una
        secuencia de ellos (una traza/apertura/cielo real por objeto,
        p. ej. `spectroscopy.multiaperture`). Reemplaza cualquier overlay
        anterior; persiste a través de cambios de stretch/STF (son items
        de escena en coordenadas de datos, independientes del píxmap)."""
        self.clear_trace_overlay()
        items = overlays if isinstance(overlays, (list, tuple)) else (overlays,)
        self._trace_overlay_single = items[0] if len(items) == 1 else None
        for i, overlay in enumerate(items):
            color = QColor(_TRACE_OVERLAY_PALETTE[i % len(_TRACE_OVERLAY_PALETTE)])
            self._draw_trace_overlay_item(overlay, color)

    def clear_trace_overlay(self) -> None:
        for item in self._trace_overlay_items:
            self._scene.removeItem(item)
        self._trace_overlay_items.clear()

    def set_calibration_windows(self, trace: TraceResult, windows: tuple[SkyWindow, ...]) -> None:
        """Añade/reemplaza las regiones reales del canal de calibración
        lateral/simultánea (§14, `lateral_calibration.py`) sobre el
        overlay ya dibujado -- si todavía no había ninguno, crea uno
        mínimo con la traza real ya conocida (`trace`, nunca inventada;
        `aperture_half_width=0.0` porque en ese caso no hay ninguna
        apertura de objeto real que mostrar todavía)."""
        base = self._trace_overlay_single or TraceOverlay(
            trace_columns=trace.columns.astype(np.float64), trace_center_px=trace.center_px,
            aperture_half_width=0.0, label="Calibración lateral",
        )
        self.set_trace_overlay(replace(base, calibration_windows=windows))

    def _draw_trace_overlay_item(self, overlay: TraceOverlay, color: QColor) -> None:
        self._add_overlay_polyline(overlay.trace_columns, overlay.trace_center_px, color, width=2.0)
        self._add_overlay_polyline(
            overlay.trace_columns, overlay.trace_center_px - overlay.aperture_half_width, color, width=1.0, dashed=True,
        )
        self._add_overlay_polyline(
            overlay.trace_columns, overlay.trace_center_px + overlay.aperture_half_width, color, width=1.0, dashed=True,
        )
        sky_color = QColor(_SKY_OVERLAY_COLOR)
        for window in overlay.sky_windows:
            lo = overlay.trace_center_px + window.offset_px - window.half_width_px
            hi = overlay.trace_center_px + window.offset_px + window.half_width_px
            self._add_overlay_polyline(overlay.trace_columns, lo, sky_color, width=1.0, dashed=True)
            self._add_overlay_polyline(overlay.trace_columns, hi, sky_color, width=1.0, dashed=True)
        calibration_color = QColor(_CALIBRATION_OVERLAY_COLOR)
        for window in overlay.calibration_windows:
            lo = overlay.trace_center_px + window.offset_px - window.half_width_px
            hi = overlay.trace_center_px + window.offset_px + window.half_width_px
            self._add_overlay_polyline(overlay.trace_columns, lo, calibration_color, width=1.0, dashed=True)
            self._add_overlay_polyline(overlay.trace_columns, hi, calibration_color, width=1.0, dashed=True)

    # ---------------------------------------------------------------- edición interactiva de la apertura (§2)
    def _nearest_trace_column_index(self, scene_x: float) -> int | None:
        overlay = self._trace_overlay_single
        if overlay is None or overlay.trace_columns.size == 0:
            return None
        index = int(round(scene_x)) - int(overlay.trace_columns[0])
        if not (0 <= index < overlay.trace_columns.size):
            return None
        return index

    def _hit_test_aperture_edge(self, scene_x: float, scene_y: float) -> bool:
        column_index = self._nearest_trace_column_index(scene_x)
        if column_index is None:
            return False
        overlay = self._trace_overlay_single
        center = float(overlay.trace_center_px[column_index])
        top, bottom = center - overlay.aperture_half_width, center + overlay.aperture_half_width
        return min(abs(scene_y - top), abs(scene_y - bottom)) <= _APERTURE_EDGE_HIT_TOLERANCE_PX

    def _aperture_half_width_for_cursor(self, scene_x: float, scene_y: float) -> float | None:
        column_index = self._nearest_trace_column_index(scene_x)
        if column_index is None:
            return None
        center = float(self._trace_overlay_single.trace_center_px[column_index])
        return max(_MIN_APERTURE_HALF_WIDTH_PX, abs(scene_y - center))

    def _add_overlay_polyline(
        self, x_values: np.ndarray, y_values: np.ndarray, color: QColor, *, width: float, dashed: bool = False,
    ) -> None:
        if x_values.size == 0:
            return
        path = QPainterPath()
        path.moveTo(float(x_values[0]), float(y_values[0]))
        for x, y in zip(x_values[1:], y_values[1:]):
            path.lineTo(float(x), float(y))
        pen = QPen(color, width)
        if dashed:
            pen.setStyle(Qt.PenStyle.DashLine)
        item = self._scene.addPath(path, pen)
        item.setZValue(10)
        self._trace_overlay_items.append(item)

    def mousePressEvent(self, event: QMouseEvent) -> None:
        if (
            not self._picking and not self.trace_overlay_locked and self._trace_overlay_single is not None
            and event.button() == Qt.MouseButton.LeftButton
        ):
            scene_pos = self.mapToScene(event.position().toPoint())
            if self._hit_test_aperture_edge(float(scene_pos.x()), float(scene_pos.y())):
                self._dragging_aperture = True
                self._live_aperture_half_width = self._trace_overlay_single.aperture_half_width
                self.setCursor(Qt.CursorShape.SizeVerCursor)
                return
        if self._picking and event.button() == Qt.MouseButton.LeftButton:
            scene_pos = self.mapToScene(event.position().toPoint())
            x, y = float(scene_pos.x()), float(scene_pos.y())
            self._picked_points.append((x, y))
            marker = self._scene.addEllipse(
                x - _MARKER_RADIUS, y - _MARKER_RADIUS, 2 * _MARKER_RADIUS, 2 * _MARKER_RADIUS,
                QPen(_MARKER_COLOR, 1.5),
            )
            self._picked_markers.append(marker)
            if self._picking_max is not None and len(self._picked_points) >= self._picking_max:
                self.finish_picking()
            return
        if self._picking and event.button() == Qt.MouseButton.RightButton:
            self.finish_picking()
            return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        scene_pos = self.mapToScene(event.position().toPoint())
        x, y = float(scene_pos.x()), float(scene_pos.y())
        height, width = self.data.shape
        ix, iy = int(x), int(y)
        value = float(self.data[iy, ix]) if 0 <= ix < width and 0 <= iy < height else float("nan")
        self.pixel_hovered.emit(x, y, value)

        if self._dragging_aperture and self._trace_overlay_single is not None:
            new_half_width = self._aperture_half_width_for_cursor(x, y)
            if new_half_width is not None:
                self._live_aperture_half_width = new_half_width
                self.clear_trace_overlay()
                self._draw_trace_overlay_item(
                    replace(self._trace_overlay_single, aperture_half_width=new_half_width), QColor(_TRACE_OVERLAY_PALETTE[0]),
                )
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event: QMouseEvent) -> None:  # noqa: N802 -- override de Qt
        if self._dragging_aperture:
            self._dragging_aperture = False
            self.unsetCursor()
            new_half_width = self._live_aperture_half_width
            if new_half_width is not None and self._trace_overlay_single is not None:
                self._trace_overlay_single = replace(self._trace_overlay_single, aperture_half_width=new_half_width)
                self.aperture_edited.emit(new_half_width)
            return
        super().mouseReleaseEvent(event)

    def dragEnterEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_PROCESS_MIME_TYPE):
            event.acceptProposedAction()

    def dragMoveEvent(self, event: QDragEnterEvent) -> None:
        if event.mimeData().hasFormat(_PROCESS_MIME_TYPE):
            event.acceptProposedAction()

    def dropEvent(self, event: QDropEvent) -> None:
        mime = event.mimeData()
        if not mime.hasFormat(_PROCESS_MIME_TYPE):
            return
        process_id = bytes(mime.data(_PROCESS_MIME_TYPE)).decode("utf-8")
        self.process_dropped.emit(process_id)
        event.acceptProposedAction()
