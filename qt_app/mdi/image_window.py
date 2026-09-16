"""Ventana de imagen dentro del área MDI -- muestra el array científico
a través del STF (nunca lo modifica), con zoom dinámico vía rueda del
ratón, tal como pide el encargo ("lupa/zoom dinámico"), y un modo de
selección de posiciones a clic para los procesos que lo necesitan
(fotometría de PSF, trazado espectral).
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QDragEnterEvent, QDropEvent, QImage, QMouseEvent, QPen, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsEllipseItem, QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from qt_app.mdi.stf import STFParams, compute_stf_params, stf_to_uint8

_PROCESS_MIME_TYPE = "application/x-astrophysics-process-id"
_MARKER_COLOR = QColor("#f0b429")
_MARKER_RADIUS = 5.0


class ImageView(QGraphicsView):
    process_dropped = Signal(str)
    """Se emite cuando se suelta un icono de proceso sobre esta vista --
    el arrastrar-y-soltar sobre una imagen que pide el encargo."""

    picking_finished = Signal(list)
    """Se emite al terminar una sesión de selección de posiciones, con la
    lista de puntos `(x_px, y_px)` marcados (posiblemente vacía si se
    canceló sin marcar ninguno)."""

    def __init__(self, data: np.ndarray, title: str, parent=None, *, wcs=None):
        super().__init__(parent)
        self.data = data
        self.title = title
        self.wcs = wcs
        """El WCS real cargado del FITS (`astropy.wcs.WCS`, o `None` si el
        archivo no tenía uno) -- disponible para cualquier proceso que
        necesite coordenadas celestes reales (p. ej. calibración
        fotométrica contra un catálogo), inyectado por `main_window`."""
        self.stf_params: STFParams = compute_stf_params(data)
        self.stf_enabled = True

        self._scene = QGraphicsScene(self)
        self.setScene(self._scene)
        self._pixmap_item = QGraphicsPixmapItem()
        self._scene.addItem(self._pixmap_item)
        self.setDragMode(QGraphicsView.DragMode.ScrollHandDrag)
        self.setRenderHint(self.renderHints())
        self.setAcceptDrops(True)

        self._display_buffer: np.ndarray | None = None
        self.refresh_display()

        self._picking = False
        self._picking_max: int | None = None
        self._picked_points: list[tuple[float, float]] = []
        self._picked_markers: list[QGraphicsEllipseItem] = []
        self._drag_mode_before_picking = self.dragMode()

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

    def mousePressEvent(self, event: QMouseEvent) -> None:
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
