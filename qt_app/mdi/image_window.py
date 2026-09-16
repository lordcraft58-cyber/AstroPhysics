"""Ventana de imagen dentro del área MDI -- muestra el array científico
a través del STF (nunca lo modifica), con zoom dinámico vía rueda del
ratón, tal como pide el encargo ("lupa/zoom dinámico").
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDragEnterEvent, QDropEvent, QImage, QPixmap, QWheelEvent
from PySide6.QtWidgets import QGraphicsPixmapItem, QGraphicsScene, QGraphicsView

from qt_app.mdi.stf import STFParams, compute_stf_params, stf_to_uint8

_PROCESS_MIME_TYPE = "application/x-astrophysics-process-id"


class ImageView(QGraphicsView):
    process_dropped = Signal(str)
    """Se emite cuando se suelta un icono de proceso sobre esta vista --
    el arrastrar-y-soltar sobre una imagen que pide el encargo."""

    def __init__(self, data: np.ndarray, title: str, parent=None):
        super().__init__(parent)
        self.data = data
        self.title = title
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
