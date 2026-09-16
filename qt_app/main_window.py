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
from PySide6.QtWidgets import QDockWidget, QFileDialog, QMainWindow, QMdiArea, QMdiSubWindow, QMessageBox, QProgressBar

from astrophysics_suite.astrometry.registration import apply_affine_transform, fit_affine_transform
from astrophysics_suite.detection.point_sources import detect_point_sources_in_array, detect_psf_candidates
from astrophysics_suite.photometry.psf import select_psf_reference_stars
from astrophysics_suite.spectroscopy.wavelength import find_arc_lines
from astrophysics_suite.tables.table import Table
from qt_app.astrometry.registration_dialog import RegistrationDialog
from qt_app.astrometry.star_pair_registration_dialog import StarPairConfigDialog
from qt_app.astrometry.plate_solve_dialog import PlateSolveDialog
from qt_app.astrometry.wcs_fit_dialog import WCSFitDialog
from qt_app.candidates.candidate_detail_widget import CandidateDetailWidget
from qt_app.candidates.candidates_dock import CandidatesDock
from qt_app.candidates.new_observation_dialog import NewObservationDialog
from qt_app.diagnostics_dialog import DiagnosticsDialog
from qt_app.docks.console_dock import ConsoleDock
from qt_app.docks.process_explorer import ProcessExplorer
from qt_app.docks.properties_dock import PropertiesDock
from qt_app.imtools.arithmetic_dialog import ArithmeticDialog
from qt_app.io.cube_plane_dialog import CubePlaneDialog
from qt_app.mdi.image_window import ImageView
from qt_app.processes.base import ProcessDefinition
from qt_app.processes.registry import build_process_registry
from qt_app.reduction.apply_calibration_dialog import ApplyCalibrationDialog
from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.reduction.reduce_session_dialog import ReduceSessionDialog, SessionReductionOutcome
from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog
from qt_app.theme import DARK, build_stylesheet
from qt_app.workers import CallableWorker, ProcessWorker
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
        self.master_frame_library = MasterFrameLibrary(self)
        self._last_result_table: Table | None = None
        """Última tabla producida por un proceso o por "Ajustar WCS..."
        -- lista para "Exportar última tabla a CSV...", `None` si nada
        con tabla se ha ejecutado todavía en esta sesión."""

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
        arithmetic_action = QAction("&Aritmética entre imágenes...", self)
        arithmetic_action.triggered.connect(self._open_arithmetic_dialog)
        tools_menu.addAction(arithmetic_action)
        export_table_action = QAction("&Exportar última tabla a CSV...", self)
        export_table_action.triggered.connect(self._export_last_table)
        tools_menu.addAction(export_table_action)

        reduction_menu = self.menuBar().addMenu("&Reducción")
        build_master_action = QAction("&Construir fotograma maestro...", self)
        build_master_action.triggered.connect(self._open_build_master_frame_dialog)
        reduction_menu.addAction(build_master_action)
        apply_calibration_action = QAction("&Aplicar calibración a la imagen activa...", self)
        apply_calibration_action.triggered.connect(self._open_apply_calibration_dialog)
        reduction_menu.addAction(apply_calibration_action)
        reduction_menu.addSeparator()
        reduce_session_action = QAction("Reducir &sesión de LIGHTS...", self)
        reduce_session_action.triggered.connect(self._open_reduce_session_dialog)
        reduction_menu.addAction(reduce_session_action)

        astrometry_menu = self.menuBar().addMenu("A&strometría")
        plate_solve_action = QAction("&Resolver placa automáticamente...", self)
        plate_solve_action.triggered.connect(self._open_plate_solve_dialog)
        astrometry_menu.addAction(plate_solve_action)
        wcs_fit_action = QAction("Ajustar WCS &manualmente (clic + coordenadas)...", self)
        wcs_fit_action.triggered.connect(self._open_wcs_fit_flow)
        astrometry_menu.addAction(wcs_fit_action)
        registration_action = QAction("&Registrar por WCS compartido...", self)
        registration_action.triggered.connect(self._open_registration_dialog)
        astrometry_menu.addAction(registration_action)
        star_pair_action = QAction("Registrar por &pares de estrellas (clic)...", self)
        star_pair_action.triggered.connect(self._open_star_pair_registration_dialog)
        astrometry_menu.addAction(star_pair_action)

        spectroscopy_menu = self.menuBar().addMenu("Espectroscop&ía")
        wavelength_fit_action = QAction("&Calibrar longitud de onda (detectar líneas)...", self)
        wavelength_fit_action.triggered.connect(self._open_wavelength_fit_flow)
        spectroscopy_menu.addAction(wavelength_fit_action)

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

    def open_fits(self, path: str) -> QMdiSubWindow | None:
        from astrophysics_suite.io.fits_loader import AmbiguousCubeError, load_image, probe_fits_shape

        try:
            loaded = load_image(path, band="", role="science")
        except AmbiguousCubeError:
            # FITS con más de 2 ejes (cubo 3D/4D): `load_fits` se niega a
            # elegir un plano por su cuenta -- se pide el índice al
            # usuario y se reintenta con `plane=` explícito, nunca se
            # asume el primero.
            try:
                shape = probe_fits_shape(path)
            except Exception as exc:  # noqa: BLE001 -- error real al inspeccionar el cubo, debe ser visible
                logger.error("No se pudo inspeccionar el cubo %s: %s", path, exc)
                QMessageBox.critical(self, "Abrir FITS", f"No se pudo leer la forma de «{Path(path).name}»:\n\n{exc}")
                return None
            dialog = CubePlaneDialog(shape, self)
            if dialog.exec() != CubePlaneDialog.DialogCode.Accepted:
                return None
            plane = dialog.selected_plane()
            try:
                loaded = load_image(path, band="", role="science", plane=plane)
            except Exception as exc:  # noqa: BLE001 -- error de carga real: debe ser visible, nunca fallar en silencio
                logger.error("No se pudo abrir %s con plano %s: %s", path, plane, exc)
                QMessageBox.critical(self, "Abrir FITS", f"No se pudo abrir «{Path(path).name}» con el plano {plane}:\n\n{exc}")
                return None
        except Exception as exc:  # noqa: BLE001 -- error de carga real: debe ser visible, nunca fallar en silencio
            logger.error("No se pudo abrir %s: %s", path, exc)
            QMessageBox.critical(self, "Abrir FITS", f"No se pudo abrir «{Path(path).name}»:\n\n{exc}")
            return None

        title = Path(path).name
        if loaded.legacy_image.selected_plane is not None:
            title = f"{title} [plano {loaded.legacy_image.selected_plane} de {loaded.legacy_image.original_shape}]"
        return self.add_image_window(
            loaded.legacy_image.data, title, wcs=loaded.legacy_image.wcs, header=loaded.legacy_image.header, source_path=str(Path(path).resolve())
        )

    def add_image_window(self, data, title: str, *, wcs=None, header: dict | None = None, source_path: str | None = None) -> QMdiSubWindow:
        view = ImageView(data, title, self, wcs=wcs, header=header, source_path=source_path)
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

    def _image_windows_by_title(self) -> dict[str, object]:
        windows: dict[str, object] = {}
        for sub_window in self.mdi.subWindowList():
            widget = sub_window.widget()
            if isinstance(widget, ImageView):
                windows[sub_window.windowTitle()] = widget.data
        return windows

    def _open_arithmetic_dialog(self) -> None:
        windows = self._image_windows_by_title()
        if len(windows) < 2:
            self.statusBar().showMessage("Abre al menos dos imágenes antes de hacer aritmética entre ellas.", 5000)
            return
        active = self._active_image_view()
        active_title = active.title if active is not None else ""
        dialog = ArithmeticDialog(windows, active_title, self)
        dialog.computed.connect(lambda data, title: self.add_image_window(data, title))
        dialog.exec()

    def _image_views_by_title(self) -> dict[str, ImageView]:
        views: dict[str, ImageView] = {}
        for sub_window in self.mdi.subWindowList():
            widget = sub_window.widget()
            if isinstance(widget, ImageView):
                views[sub_window.windowTitle()] = widget
        return views

    def _open_registration_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage("Abre al menos dos imágenes antes de registrar una contra la otra.", 5000)
            return
        active = self._active_image_view()
        active_title = active.title if active is not None else ""
        dialog = RegistrationDialog(views, active_title, self)
        dialog.computed.connect(lambda data, title: self.add_image_window(data, title))
        dialog.exec()

    def _open_star_pair_registration_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage("Abre al menos dos imágenes antes de registrar por pares de estrellas.", 5000)
            return
        active = self._active_image_view()
        active_title = active.title if active is not None else ""
        dialog = StarPairConfigDialog(list(views.keys()), active_title, self)
        if dialog.exec() != StarPairConfigDialog.DialogCode.Accepted:
            return

        reference_title, target_title = dialog.reference_title(), dialog.target_title()
        if reference_title == target_title:
            self.statusBar().showMessage("Elige dos ventanas distintas.", 5000)
            return
        self._start_star_pair_picking(views[reference_title], views[target_title], reference_title, target_title, dialog.model(), dialog.n_pairs())

    def _start_star_pair_picking(
        self, reference_view: ImageView, target_view: ImageView, reference_title: str, target_title: str, model: str, n_pairs: int
    ) -> None:
        """Recoge `n_pairs` posiciones en `reference_view`, luego el mismo
        número en `target_view` -- ambas ventanas ya soportan clic-para-
        marcar de forma independiente (Fase 9.6 §8), así que encadenar dos
        sesiones de selección en dos `ImageView` distintas no necesita
        ninguna interacción nueva, solo orquestar el orden."""
        self.statusBar().showMessage(
            f"Registro por pares: marca {n_pairs} estrella(s) en «{reference_title}» (referencia) -- clic derecho para terminar antes de tiempo."
        )

        def on_reference_picked(reference_points: list[tuple[float, float]]) -> None:
            reference_view.picking_finished.disconnect(on_reference_picked)
            if len(reference_points) < 3:
                self.statusBar().showMessage(f"Se necesitan al menos 3 pares -- solo se marcaron {len(reference_points)} en «{reference_title}».", 6000)
                return

            self.statusBar().showMessage(
                f"Ahora marca las MISMAS {len(reference_points)} estrella(s), en el mismo orden, en «{target_title}» -- clic derecho para terminar."
            )

            def on_target_picked(target_points: list[tuple[float, float]]) -> None:
                target_view.picking_finished.disconnect(on_target_picked)
                if len(target_points) != len(reference_points):
                    self.statusBar().showMessage(
                        f"Se marcaron {len(target_points)} punto(s) en «{target_title}», pero {len(reference_points)} en «{reference_title}» -- deben coincidir en número y orden. Inténtalo de nuevo.",
                        7000,
                    )
                    return
                self._compute_star_pair_registration(reference_view, target_view, reference_title, target_title, reference_points, target_points, model)

            target_view.picking_finished.connect(on_target_picked)
            target_view.start_picking(max_points=n_pairs)

        reference_view.picking_finished.connect(on_reference_picked)
        reference_view.start_picking(max_points=n_pairs)

    def _compute_star_pair_registration(
        self,
        reference_view: ImageView,
        target_view: ImageView,
        reference_title: str,
        target_title: str,
        reference_points: list[tuple[float, float]],
        target_points: list[tuple[float, float]],
        model: str,
    ) -> None:
        self.statusBar().showMessage("Ajustando transformación afín entre los pares marcados...")
        target_data = target_view.data
        output_shape = reference_view.data.shape

        def run() -> tuple:
            # `fit_affine_transform(reference_xy, target_xy)` da una
            # transformación reference_xy -> target_xy; aquí queremos
            # remuestrear los datos de `target_view` sobre la REJILLA de
            # `reference_view`, así que el papel "reference" del ajuste lo
            # ocupan los puntos de target_view (el sistema de origen de los
            # datos a transformar) y el papel "target" lo ocupan los puntos
            # de reference_view (la rejilla de salida deseada) -- ver
            # docstring de `apply_affine_transform`.
            transform = fit_affine_transform(target_points, reference_points, model=model)
            resampled = apply_affine_transform(target_data, transform, output_shape=output_shape)
            return transform, resampled, model

        worker = CallableWorker(run, self)
        worker.finished_ok.connect(lambda result: self._on_star_pair_registration_done(result, reference_title, target_title))
        worker.failed.connect(self._on_process_failed)
        self._active_worker = worker
        worker.finished.connect(lambda: setattr(self, "_active_worker", None))
        worker.start()

    def _on_star_pair_registration_done(self, result: tuple, reference_title: str, target_title: str) -> None:
        transform, resampled, model = result
        title = f"{target_title} -> pares con {reference_title}"
        self.add_image_window(resampled, title)
        logger.info(
            "Registro por pares de estrellas: %s -> %s, RMS=%.3f px con %d par(es), modelo=%s",
            target_title, reference_title, transform.rms_residual_px, transform.n_points, model,
        )
        self.statusBar().showMessage(f"Registro por pares completado (RMS={transform.rms_residual_px:.2f} px, {transform.n_points} par(es)).", 6000)

    def _open_plate_solve_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de resolver la placa.", 5000)
            return
        dialog = PlateSolveDialog(view.data, view.header, self)
        if dialog.exec() != PlateSolveDialog.DialogCode.Accepted:
            return
        solution = dialog.result_solution()
        if solution is None:
            return
        view.fitted_wcs_solution = solution
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table
        logger.info(
            "Placa resuelta automáticamente para %s: RMS=%.3f\" con %d estrella(s).",
            view.title, solution.rms_residual_arcsec, solution.n_stars,
        )
        self.statusBar().showMessage(f"WCS resuelto automáticamente para {view.title} (RMS={solution.rms_residual_arcsec:.3f}\").", 6000)
        self._offer_to_save_wcs_fits_copy(view, solution)

    def _offer_to_save_wcs_fits_copy(self, view: ImageView, solution) -> None:
        reply = QMessageBox.question(
            self, "Guardar copia con WCS",
            "¿Guardar una copia del FITS con el WCS resuelto escrito en la cabecera?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        default_path = ""
        if view.source_path:
            source = Path(view.source_path)
            default_path = str(source.with_name(f"{source.stem}_wcs{source.suffix}"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar FITS con WCS", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return

        from astrophysics_suite.astrometry.wcs_fit import wcs_solution_to_astropy
        from astrophysics_suite.io.fits_writer import save_fits_image

        astropy_wcs = wcs_solution_to_astropy(solution)
        header = dict(view.header) if view.header else {}
        header.update(dict(astropy_wcs.to_header()))
        try:
            save_fits_image(path, view.data, header=header)
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar %s: %s", path, exc)
            QMessageBox.critical(self, "Guardar FITS con WCS", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("FITS con WCS guardado en %s", path)
        self.statusBar().showMessage(f"FITS con WCS guardado en {path}", 6000)

    def _open_wcs_fit_flow(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de ajustar un WCS.", 5000)
            return
        self.statusBar().showMessage("Ajustar WCS: haz clic en cada estrella de referencia -- clic derecho para terminar.")

        def on_picked(points: list[tuple[float, float]]) -> None:
            view.picking_finished.disconnect(on_picked)
            if len(points) < 3:
                self.statusBar().showMessage("Se necesitan al menos 3 estrellas para ajustar un WCS.", 5000)
                return
            dialog = WCSFitDialog(points, view.data.shape, self)
            dialog.fitted.connect(lambda solution, table, v=view: self._on_wcs_fitted(v, solution, table))
            dialog.exec()

        view.picking_finished.connect(on_picked)
        view.start_picking()

    def _on_wcs_fitted(self, view: ImageView, solution, table: Table) -> None:
        view.fitted_wcs_solution = solution
        self._last_result_table = table
        logger.info(
            "WCS ajustado para %s: RMS=%.3f\" con %d estrella(s). Tabla disponible -- Herramientas -> Exportar última tabla a CSV...",
            view.title, solution.rms_residual_arcsec, solution.n_stars,
        )
        self.statusBar().showMessage(f"WCS ajustado para {view.title} (RMS={solution.rms_residual_arcsec:.3f}\").", 6000)

    def _export_last_table(self) -> None:
        if self._last_result_table is None:
            self.statusBar().showMessage("No hay ninguna tabla que exportar todavía -- ejecuta un proceso que produzca una (p. ej. punto cero, ajuste de WCS).", 6000)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar tabla a CSV", "", "CSV (*.csv)")
        if not path:
            return
        self._last_result_table.to_csv(path)
        self.statusBar().showMessage(f"Tabla exportada a {path}", 5000)

    def _open_wavelength_fit_flow(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de calibrar longitud de onda.", 5000)
            return

        # misma convención que spectroscopy.continuum: la fila central de
        # la imagen tratada como espectro 1D de arco, mientras el taller
        # no tiene un flujo dedicado de extracción de arco.
        row_index = view.data.shape[0] // 2
        spectrum = view.data[row_index, :].astype(float)
        lines = find_arc_lines(spectrum)
        if len(lines) < 2:
            self.statusBar().showMessage(f"Solo se detectaron {len(lines)} línea(s) de arco en la fila central -- se necesitan más para un ajuste.", 6000)
            return

        dialog = WavelengthFitDialog(lines, self)
        dialog.fitted.connect(lambda solution, table, v=view: self._on_wavelength_fitted(v, solution, table))
        dialog.exec()

    def _on_wavelength_fitted(self, view: ImageView, solution, table: Table) -> None:
        view.fitted_wavelength_solution = solution
        self._last_result_table = table
        logger.info(
            "Longitud de onda calibrada para %s: RMS=%.4f (grado %d, %d línea(s)). Tabla disponible -- Herramientas -> Exportar última tabla a CSV...",
            view.title, solution.rms_residual, solution.degree, len(table.rows),
        )
        self.statusBar().showMessage(f"Longitud de onda calibrada para {view.title} (RMS={solution.rms_residual:.4f}).", 6000)

    def _open_build_master_frame_dialog(self) -> None:
        dialog = BuildMasterFrameDialog(self.master_frame_library, self)
        if dialog.exec() == BuildMasterFrameDialog.DialogCode.Accepted:
            logger.info("Fotograma maestro construido: %s", dialog.name_edit.text().strip())

    def _open_apply_calibration_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de calibrar.", 5000)
            return
        if len(self.master_frame_library) == 0:
            self.statusBar().showMessage("Construye al menos un fotograma maestro antes de calibrar.", 5000)
            return
        dialog = ApplyCalibrationDialog(self.master_frame_library, view.data, self)
        dialog.calibrated.connect(lambda data, summary, v=view: self._on_calibration_applied(v, data, summary))
        dialog.exec()

    def _on_calibration_applied(self, view: ImageView, data, summary: str) -> None:
        logger.info("Calibración aplicada a %s: %s", view.title, summary)
        self.add_image_window(data, f"{view.title} -> calibrada")

    def _open_reduce_session_dialog(self) -> None:
        dialog = ReduceSessionDialog(self.master_frame_library, self)
        dialog.session_reduced.connect(self._on_session_reduced)
        dialog.exec()

    def _on_session_reduced(self, outcome: SessionReductionOutcome) -> None:
        logger.info(
            "Sesión reducida: %d LIGHT(s) calibrado(s) y escrito(s) a disco%s",
            outcome.n_frames,
            f"; combinado en {outcome.combined_path}" if outcome.combined_path else "",
        )
        for path in outcome.output_paths:
            logger.info("  -> %s", path)
        if outcome.combined_data is not None and outcome.combined_path is not None:
            self.add_image_window(outcome.combined_data, Path(outcome.combined_path).name)

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

        if process.process_id == "photometry.psf" and params.get("use_empirical_psf"):
            self._start_empirical_psf_picking(process, view, params)
            return

        if process.requires_picking is not None and params.get("auto_detect"):
            self._run_with_auto_detected_points(process, view, params)
            return

        if process.requires_picking is not None:
            self._start_picking_then_run(process, view, params)
            return

        self._start_process_worker(process, view, params)

    def _start_empirical_psf_picking(self, process: ProcessDefinition, view: ImageView, params: dict) -> None:
        """`photometry.psf` con "Usar PSF empírica" activo necesita DOS
        sesiones de clic encadenadas en la misma ventana -- primero las
        estrellas de referencia con las que construir la PSF, luego las
        fuentes a medir con ella -- en vez de la única sesión que usa el
        resto de procesos. Mismo mecanismo de picking ya existente,
        encadenado dos veces (mismo patrón que el registro por pares de
        estrellas entre dos ventanas de la Fase 18)."""
        self.statusBar().showMessage(
            "PSF empírica: marca las estrellas de REFERENCIA para construir la PSF (clic izq. marca, clic derecho termina)."
        )
        self.properties.apply_button.setEnabled(False)

        def on_reference_picked(reference_points: list[tuple[float, float]]) -> None:
            view.picking_finished.disconnect(on_reference_picked)
            if not reference_points:
                self.properties.apply_button.setEnabled(True)
                self.statusBar().showMessage("Selección cancelada: no se marcó ninguna estrella de referencia para la PSF empírica.", 6000)
                return

            self.statusBar().showMessage(
                f"PSF empírica: {len(reference_points)} estrella(s) de referencia marcada(s). Ahora marca las FUENTES A MEDIR -- clic derecho para terminar."
            )

            def on_target_picked(target_points: list[tuple[float, float]]) -> None:
                view.picking_finished.disconnect(on_target_picked)
                if not target_points:
                    self.properties.apply_button.setEnabled(True)
                    self.statusBar().showMessage("Selección cancelada: no se marcó ninguna fuente a medir.", 6000)
                    return
                picked_params = dict(params)
                picked_params["_psf_reference_points"] = reference_points
                picked_params["_picked_points"] = target_points
                self._start_process_worker(process, view, picked_params)

            view.picking_finished.connect(on_target_picked)
            view.start_picking()

        view.picking_finished.connect(on_reference_picked)
        view.start_picking()

    def _run_with_auto_detected_points(self, process: ProcessDefinition, view: ImageView, params: dict) -> None:
        """Alternativa a `_start_picking_then_run` para procesos con
        `ParameterSpec("auto_detect", ...)`: detecta fuentes reales
        (DAOStarFinder) en la imagen activa y las usa directamente como
        `_picked_points`, sin exigir clics manuales -- un radio de
        `requires_picking=1` usa solo la más brillante; `0` (ilimitado)
        usa hasta 20, de más a menos brillante. `photometry.psf` usa en su
        lugar la selección tipo `pstselect` (aislamiento + redondez +
        señal/ruido), no solo brillo -- una estrella de referencia para
        PSF necesita estar aislada, no simplemente ser brillante."""
        fwhm_px = float(params.get("detect_fwhm_px", 3.0))
        threshold_sigma = float(params.get("detect_threshold_sigma", 5.0))

        if process.process_id == "photometry.psf":
            candidates = detect_psf_candidates(view.data, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma)
            selected = select_psf_reference_stars(
                candidates,
                min_separation_px=float(params.get("psf_min_separation_px", 15.0)),
                max_ellipticity=float(params.get("psf_max_ellipticity", 0.3)),
                min_snr=float(params.get("psf_min_snr", 15.0)),
                max_stars=int(params.get("psf_max_stars", 12)),
            )
            if not selected:
                self.statusBar().showMessage(
                    "Selección automática (pstselect): ninguna fuente detectada cumple los criterios de aislamiento/redondez/S-N -- ajústalos o marca las posiciones a mano.",
                    7000,
                )
                return
            points = [(c.x, c.y) for c in selected]
            message = f"Selección automática (pstselect): {len(points)} estrella(s) de referencia (de {len(candidates)} detectada(s))."
        else:
            sources = detect_point_sources_in_array(view.data, fwhm_px=fwhm_px, threshold_sigma=threshold_sigma)
            if not sources:
                self.statusBar().showMessage(
                    "Detección automática: no se encontró ninguna fuente por encima del umbral -- baja el umbral o marca la posición a mano.", 6000
                )
                return
            max_points = process.requires_picking if process.requires_picking else 20
            points = [(x, y) for x, y, _flux in sources[:max_points]]
            message = f"Detección automática: {len(points)} fuente(s) usada(s) (de {len(sources)} detectada(s) en total)."

        picked_params = dict(params)
        picked_params["_picked_points"] = points
        self.statusBar().showMessage(message, 5000)
        self._start_process_worker(process, view, picked_params)

    def _start_picking_then_run(self, process: ProcessDefinition, view: ImageView, params: dict) -> None:
        max_points = process.requires_picking if process.requires_picking else None
        hint = f" ({max_points})" if max_points else ""
        self.statusBar().showMessage(f"{process.name}: haz clic sobre la imagen para marcar posiciones{hint} -- clic derecho para terminar.")
        self.properties.apply_button.setEnabled(False)

        def on_picked(points: list[tuple[float, float]]) -> None:
            view.picking_finished.disconnect(on_picked)
            if not points:
                self.properties.apply_button.setEnabled(True)
                self.statusBar().showMessage("Selección cancelada: no se marcó ninguna posición.", 5000)
                return
            picked_params = dict(params)
            picked_params["_picked_points"] = points
            self._start_process_worker(process, view, picked_params)

        view.picking_finished.connect(on_picked)
        view.start_picking(max_points=max_points)

    def _start_process_worker(self, process: ProcessDefinition, view: ImageView, params: dict) -> None:
        self.statusBar().showMessage(f"Ejecutando: {process.name}...")
        self.properties.apply_button.setEnabled(False)

        params = dict(params)
        params["_wcs"] = view.wcs

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
        if result.table is not None:
            self._last_result_table = result.table
            logger.info("    Tabla disponible (%d fila(s)) -- Herramientas -> Exportar última tabla a CSV...", len(result.table.rows))

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
