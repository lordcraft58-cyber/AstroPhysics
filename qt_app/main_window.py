"""Ventana principal del taller -- orquesta el explorador de procesos,
el área MDI de imágenes, la consola y el panel de propiedades. Nunca
contiene lógica científica: cada proceso llama a `astrophysics_suite.*`
a través de `qt_app.processes.registry` (misma disciplina que ya regía
`gui/app.py` en la Fase 8).
"""
from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMdiArea, QMdiSubWindow, QProgressBar

from qt_app.candidates.candidate_detail_widget import CandidateDetailWidget
from qt_app.candidates.candidates_dock import CandidatesDock
from qt_app.candidates.new_observation_dialog import NewObservationDialog
from qt_app.diagnostics_dialog import DiagnosticsDialog
from qt_app.docks.console_dock import ConsoleDock
from qt_app.docks.process_explorer import ProcessExplorer
from qt_app.docks.properties_dock import PropertiesDock
from qt_app.mdi.image_window import ImageView
from qt_app.processes.base import ProcessDefinition
from qt_app.processes.registry import build_process_registry
from qt_app.theme import DARK, build_stylesheet
from qt_app.workers import ProcessWorker
from services.discovery_service import DiscoveryJob, DiscoveryParams
from services.session_state import SessionState

APP_TITLE = "AstroPhysics Suite -- Taller de Procesamiento"
PIPELINE_VERSION = "0.5.0-dev"
DISCOVERY_POLL_MS = 100

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

        self.session_state = SessionState()
        self._discovery_job: DiscoveryJob | None = None
        self._discovery_timer: QTimer | None = None
        self._candidate_detail_windows: dict[str, QMdiSubWindow] = {}

        self._build_docks()
        self._build_menu()
        self._build_status_bar()
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

        self.candidates_dock_widget = CandidatesDock(self.session_state, DARK, self)
        self.candidates_dock_widget.candidate_activated.connect(self._open_candidate_detail)
        candidates_dock = QDockWidget("CANDIDATOS", self)
        candidates_dock.setObjectName("CandidatesDock")
        candidates_dock.setWidget(self.candidates_dock_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, candidates_dock)
        self.tabifyDockWidget(properties_dock, candidates_dock)
        properties_dock.raise_()

    def _build_status_bar(self) -> None:
        self.discovery_progress = QProgressBar(self)
        self.discovery_progress.setMaximumWidth(220)
        self.discovery_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.discovery_progress)

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

        tools_menu = self.menuBar().addMenu("&Herramientas")
        diagnostics_action = QAction("&Diagnóstico de equipo...", self)
        diagnostics_action.triggered.connect(self._open_diagnostics_dialog)
        tools_menu.addAction(diagnostics_action)

        view_menu = self.menuBar().addMenu("&Vista")
        stf_action = QAction("Alternar STF en la imagen activa", self)
        stf_action.setShortcut("Ctrl+T")
        stf_action.triggered.connect(self._toggle_active_stf)
        view_menu.addAction(stf_action)

        discovery_menu = self.menuBar().addMenu("&Descubrimiento")
        new_observation_action = QAction("&Nueva observación...", self)
        new_observation_action.setShortcut("Ctrl+N")
        new_observation_action.triggered.connect(self._open_new_observation_dialog)
        discovery_menu.addAction(new_observation_action)
        self.cancel_discovery_action = QAction("&Cancelar análisis", self)
        self.cancel_discovery_action.setEnabled(False)
        self.cancel_discovery_action.triggered.connect(self._cancel_discovery)
        discovery_menu.addAction(self.cancel_discovery_action)

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

    def _open_diagnostics_dialog(self) -> None:
        dialog = DiagnosticsDialog(self)
        dialog.exec()

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

    # ---------------------------------------------------------------- descubrimiento
    def _open_new_observation_dialog(self) -> None:
        if self._discovery_job is not None:
            self.statusBar().showMessage("Ya hay un análisis en curso; espera a que termine.", 5000)
            return
        dialog = NewObservationDialog(self)
        if dialog.exec() != NewObservationDialog.DialogCode.Accepted:
            return
        self._start_discovery(dialog.result_target_name(), dialog.result_images())

    def _start_discovery(self, target_name: str, images: list[tuple[str, str]]) -> None:
        self._discovery_job = DiscoveryJob(
            target_name=target_name, images=images, params=DiscoveryParams(), pipeline_version=PIPELINE_VERSION
        )
        self._discovery_job.start()
        self.discovery_progress.setVisible(True)
        self.discovery_progress.setValue(0)
        self.cancel_discovery_action.setEnabled(True)
        self.statusBar().showMessage(f"Analizando {target_name}...")

        self._discovery_timer = QTimer(self)
        self._discovery_timer.timeout.connect(self._poll_discovery)
        self._discovery_timer.start(DISCOVERY_POLL_MS)

    def _poll_discovery(self) -> None:
        job = self._discovery_job
        if job is None:
            if self._discovery_timer is not None:
                self._discovery_timer.stop()
            return

        for event in job.poll():
            if event.kind == "progress":
                self.discovery_progress.setValue(int(event.fraction * 100))
                self.statusBar().showMessage(event.message)
            elif event.kind == "done":
                self.session_state.add_observation(event.observation, event.loaded_images)
                self.session_state.add_candidates(list(event.candidates))
                logger.info(
                    "Descubrimiento completado: %d candidatos de %d detecciones (%d rechazados como artefacto)",
                    event.summary.n_candidates, event.summary.n_detected, event.summary.n_artifact_rejected,
                )
                self.statusBar().showMessage(f"Completado: {event.summary.n_candidates} candidatos de {event.summary.n_detected} detecciones.", 8000)
                self._finish_discovery()
                return
            elif event.kind == "cancelled":
                self.statusBar().showMessage(event.message or "Análisis cancelado.", 5000)
                self._finish_discovery()
                return
            elif event.kind == "error":
                logger.error("Descubrimiento falló: %s", event.message)
                self.statusBar().showMessage(f"Error en el análisis: {event.message}", 8000)
                self._finish_discovery()
                return

    def _finish_discovery(self) -> None:
        if self._discovery_timer is not None:
            self._discovery_timer.stop()
            self._discovery_timer = None
        self._discovery_job = None
        self.discovery_progress.setVisible(False)
        self.cancel_discovery_action.setEnabled(False)

    def _cancel_discovery(self) -> None:
        if self._discovery_job is not None:
            self._discovery_job.cancel()

    # ---------------------------------------------------------------- candidatos
    def _open_candidate_detail(self, candidate_id: str) -> None:
        existing = self._candidate_detail_windows.get(candidate_id)
        if existing is not None:
            self.mdi.setActiveSubWindow(existing)
            return

        widget = CandidateDetailWidget(candidate_id, self.session_state, DARK, self)
        sub_window = QMdiSubWindow()
        sub_window.setWidget(widget)
        sub_window.setWindowTitle(f"Candidato: {candidate_id}")
        sub_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.mdi.addSubWindow(sub_window)
        sub_window.resize(560, 680)
        sub_window.show()

        self._candidate_detail_windows[candidate_id] = sub_window
        sub_window.destroyed.connect(lambda: self._candidate_detail_windows.pop(candidate_id, None))
