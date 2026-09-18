"""Explorador de procesos -- panel lateral con el árbol categorizado de
algoritmos, tal como pide el encargo. Doble clic (o arrastrar sobre una
ventana de imagen, ver `main_window.py`) abre el proceso en el panel de
propiedades.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem

from qt_app.processes.base import ProcessDefinition

PROCESS_ID_ROLE = Qt.ItemDataRole.UserRole


class ProcessExplorer(QTreeWidget):
    process_activated = Signal(str)

    def __init__(self, processes: list[ProcessDefinition], parent=None):
        super().__init__(parent)
        self.setHeaderHidden(True)
        self.setDragEnabled(True)
        self._processes_by_id = {p.process_id: p for p in processes}
        self._populate(processes)
        self.itemDoubleClicked.connect(self._on_item_double_clicked)

    def _populate(self, processes: list[ProcessDefinition]) -> None:
        categories: dict[str, QTreeWidgetItem] = {}
        for process in sorted(processes, key=lambda p: (p.category, p.name)):
            category_item = categories.get(process.category)
            if category_item is None:
                category_item = QTreeWidgetItem(self, [process.category])
                category_item.setFlags(category_item.flags() & ~Qt.ItemFlag.ItemIsSelectable)
                categories[process.category] = category_item
                self.addTopLevelItem(category_item)

            label = process.name if process.is_wired else f"{process.name}  (pendiente)"
            leaf = QTreeWidgetItem(category_item, [label])
            leaf.setData(0, PROCESS_ID_ROLE, process.process_id)
            if not process.is_wired:
                leaf.setForeground(0, self.palette().mid())
            leaf.setToolTip(0, process.description)

        self.expandAll()

    def _on_item_double_clicked(self, item: QTreeWidgetItem, _column: int) -> None:
        process_id = item.data(0, PROCESS_ID_ROLE)
        if process_id:
            self.process_activated.emit(process_id)

    def startDrag(self, supportedActions) -> None:  # noqa: N802 -- override de Qt
        item = self.currentItem()
        if item is None:
            return
        process_id = item.data(0, PROCESS_ID_ROLE)
        if not process_id:
            return
        from PySide6.QtCore import QMimeData

        mime = QMimeData()
        mime.setData("application/x-astrophysics-process-id", process_id.encode("utf-8"))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.DropAction.CopyAction)
