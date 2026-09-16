"""Ventana principal del taller -- orquesta el explorador de procesos,
el área MDI de imágenes, la consola y el panel de propiedades. Nunca
contiene lógica científica: cada proceso llama a `astrophysics_suite.*`
a través de `qt_app.processes.registry` (misma disciplina que ya regía
`gui/app.py` en la Fase 8).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMdiArea, QMdiSubWindow

from qt_app.docks.console_dock import ConsoleDock
from qt_app.docks.process_explorer import ProcessExplorer
from qt_app.docks.properties_dock import PropertiesDock
from qt_app.mdi.image_window import ImageView
from qt_app.processes.base import ProcessDefinition
from qt_app.processes.registry import build_process_registry
from qt_app.theme import DARK, build_stylesheet
from qt_app.workers import ProcessWorker

APP_TITLE = "AstroPhysics Suite -- Taller de Procesamiento"

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1440, 920)
        self.setStyleSheet(build_stylesheet(DARK))

        self.mdi = QMdiArea(self)
        self.mdi.setViewMode(QMdiArea.ViewMode.SubWindowView)
        # QMdiArea pinta su fondo desde la paleta, no desde la hoja de
        # estilos QSS -- un `background` en el QSS no lo alcanza; hay que
        # fijarlo por paleta para que no se quede con el gris por defecto
        # de Qt en medio de un tema oscuro.
        self.mdi.setBackground(QColor(DARK.bg_input))
        self.setCentralWidget(self.mdi)

        self._processes: list[ProcessDefinition] = build_process_registry()
        self._process_by_id = {p.process_id: p for p in self._processes}
        self._active_worker: ProcessWorker | None = None

        self._build_docks()
        self._build_menu()
        self.statusBar().showMessage("Listo")

    # ---------------------------------------------------------------- docks
    def _build_docks(self) -> None:
        self.explorer = ProcessExplorer(self._processes, self)
        self.explorer.process_activated.connect(self._activate_process)
        explorer_dock = QDockWidget("EXPLORADOR DE PROCESOS", self)
        explorer_dock.setObjectName("ExplorerDock")
        explorer_dock.setWidget(self.explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, explorer_dock)

        self.properties = PropertiesDock(self)
        self.properties.run_requested.connect(self._run_process)
        properties_dock = QDockWidget("PROPIEDADES", self)
        properties_dock.setObjectName("PropertiesDock")
        properties_dock.setWidget(self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, properties_dock)

        self.console = ConsoleDock(self)
        console_dock = QDockWidget("CONSOLA", self)
        console_dock.setObjectName("ConsoleDock")
        console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, console_dock)

    # ---------------------------------------------------------------- menú
    def _build_menu(self) -> None:
        file_menu = self.menuBar().addMenu("&Archivo")
        open_action = QAction("&Abrir FITS...", self)
        open_action.setShortcut("Ctrl+O")
        open_action.triggered.connect(self.open_fits_dialog)
        file_menu.addAction(open_action)
        file_menu.addSeparator()
        exit_action = QAction("&Salir", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        file_menu.addAction(exit_action)

        view_menu = self.menuBar().addMenu("&Vista")
        stf_action = QAction("Alternar STF en la imagen activa", self)
        stf_action.setShortcut("Ctrl+T")
        stf_action.triggered.connect(self._toggle_active_stf)
        view_menu.addAction(stf_action)

    # ---------------------------------------------------------------- imágenes
    def open_fits_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir FITS", "", "FITS (*.fits *.fit *.fts);;Todos los archivos (*.*)")
        if path:
            self.open_fits(path)

    def open_fits(self, path: str) -> QMdiSubWindow:
        from astrophysics_suite.io.fits_loader import load_image

        loaded = load_image(path, band="", role="science")
        return self.add_image_window(loaded.legacy_image.data, Path(path).name)

    def add_image_window(self, data, title: str) -> QMdiSubWindow:
        view = ImageView(data, title, self)
        view.process_dropped.connect(lambda process_id, v=view: self._on_process_dropped(process_id, v))

        sub_window = QMdiSubWindow()
        sub_window.setWidget(view)
        sub_window.setWindowTitle(title)
        sub_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.mdi.addSubWindow(sub_window)
        sub_window.resize(560, 560)
        sub_window.show()

        logger.info("Imagen cargada: %s (%d x %d)", title, data.shape[1], data.shape[0])
        return sub_window

    def _active_image_view(self) -> ImageView | None:
        sub_window = self.mdi.activeSubWindow()
        if sub_window is None:
            return None
        return sub_window.widget()

    def _toggle_active_stf(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("No hay ninguna imagen activa.", 4000)
            return
        view.set_stf_enabled(not view.stf_enabled)

    # ---------------------------------------------------------------- procesos
    def _activate_process(self, process_id: str) -> None:
        self.properties.set_process(self._process_by_id[process_id])

    def _on_process_dropped(self, process_id: str, view: ImageView) -> None:
        """Arrastrar un icono de proceso sobre una vista la selecciona
        como destino y abre sus parámetros -- el usuario confirma con
        "Aplicar" (ver `properties_dock.py`); soltar nunca ejecuta nada
        por sí solo."""
        sub_window = view.parentWidget()
        if isinstance(sub_window, QMdiSubWindow):
            self.mdi.setActiveSubWindow(sub_window)
        self.properties.set_process(self._process_by_id[process_id])

    def _run_process(self, process_id: str, params: dict) -> None:
        process = self._process_by_id[process_id]
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de aplicar un proceso.", 5000)
            return

        self.statusBar().showMessage(f"Ejecutando: {process.name}...")
        self.properties.apply_button.setEnabled(False)

        worker = ProcessWorker(process.run, view.data, params, self)
        worker.finished_ok.connect(lambda result, p=process, v=view: self._on_process_finished(p, v, result))
        worker.failed.connect(self._on_process_failed)
        worker.finished.connect(lambda: setattr(self, "_active_worker", None))
        self._active_worker = worker
        worker.start()

    def _on_process_finished(self, process: ProcessDefinition, view: ImageView, result) -> None:
        self.properties.apply_button.setEnabled(True)
        self.statusBar().showMessage(f"{process.name}: completado", 5000)
        logger.info("[%s] %s", process.name, result.summary)
        for line in result.log_lines:
            logger.info("    %s", line)
        if result.output_data is not None:
            self.add_image_window(result.output_data, f"{view.title} -> {process.name}")

    def _on_process_failed(self, message: str) -> None:
        self.properties.apply_button.setEnabled(True)
        self.statusBar().showMessage("Error al ejecutar el proceso", 5000)
        logger.error("%s", message)
