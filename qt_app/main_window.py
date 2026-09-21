"""Ventana principal del taller -- orquesta el explorador de procesos,
el área MDI de imágenes, la consola y el panel de propiedades. Nunca
contiene lógica científica: cada proceso llama a `astrophysics_suite.*`
a través de `qt_app.processes.registry` (misma disciplina que ya regía
`gui/app.py` en la Fase 8).
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QAction, QColor
from PySide6.QtWidgets import QDockWidget, QFileDialog, QInputDialog, QLabel, QMainWindow, QMdiArea, QMdiSubWindow, QMessageBox, QProgressBar

from astrophysics_suite.astrometry.provenance import SOURCE_MANUAL_FIT, SOURCE_OPTICS, RegistrationRecord, WCSRecord
from astrophysics_suite.spectroscopy.calibration_provenance import build_wavelength_provenance
from astrophysics_suite.astrometry.registration import apply_affine_transform, fit_affine_transform
from astrophysics_suite.detection.point_sources import detect_point_sources_in_array, detect_psf_candidates
from astrophysics_suite.discovery.pipeline import (
    WCS_STATE_AUTO_RESOLVED,
    WCS_STATE_BLIND_RESOLVED,
    WCS_STATE_SOLVE_FAILED,
    WCS_STATE_SOLVE_NOT_RUN,
)
from astrophysics_suite.photometry.psf import select_psf_reference_stars
from astrophysics_suite.spectroscopy.multiaperture import find_aperture_centers
from astrophysics_suite.spectroscopy.processing_history import ProcessingHistoryEntry, append_processing_history
from astrophysics_suite.spectroscopy.wavelength import find_arc_lines
from astrophysics_suite.tables.table import Table
from qt_app.astrometry.registration_dialog import RegistrationDialog, RegistrationOutcome
from qt_app.astrometry.star_pair_registration_dialog import StarPairConfigDialog
from qt_app.astrometry.blind_solve_dialog import BlindPlateSolveDialog
from qt_app.astrometry.optical_wcs_dialog import OpticalWCSDialog
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
from qt_app.reduction.apply_calibration_dialog import ApplyCalibrationDialog, CalibrationOutcome
from qt_app.reduction.build_master_frame_dialog import BuildMasterFrameDialog
from qt_app.reduction.master_frame_library import MasterFrameLibrary
from qt_app.reduction.reduce_session_dialog import ReduceSessionDialog, SessionReductionOutcome
from qt_app.spectroscopy.combine_spectra_dialog import CombineSpectraDialog
from qt_app.spectroscopy.template_comparison_dialog import TemplateComparisonDialog
from qt_app.spectroscopy.trace_overlay_data import recalculate_extraction
from qt_app.spectroscopy.flexure_correction_dialog import FlexureCorrectionDialog
from qt_app.spectroscopy.telluric_correction_dialog import TelluricCorrectionDialog
from qt_app.spectroscopy.flux_calibration_dialog import FluxCalibrationDialog
from qt_app.spectroscopy.radial_velocity_dialog import RadialVelocityDialog
from qt_app.spectroscopy.spectrum_plot_data import SpectrumPlotData, SpectrumSeries
from qt_app.spectroscopy.spectrum_view import SpectrumView
from qt_app.spectroscopy.synthetic_photometry_dialog import SyntheticPhotometryDialog
from qt_app.spectroscopy.wavelength_fit_dialog import WavelengthFitDialog
from qt_app.theme import DARK, build_stylesheet
from qt_app.tutorial.tutorial_overlay import TutorialOverlay
from qt_app.tutorial.tutorial_steps import build_tutorial_steps
from qt_app.workers import CallableWorker, ProcessWorker
from services.app_preferences import AppPreferencesStore
from services.instrument_profiles import InstrumentProfileStore
from services.discovery_service import DiscoveryJob, DiscoveryParams
from services.session_state import SessionState

_TUTORIAL_SHOW_ON_STARTUP_KEY = "tutorial_show_on_startup"
_RECENT_SESSIONS_PREFERENCE_KEY = "recent_sessions"
_MAX_RECENT_SESSIONS = 8

APP_TITLE = "AstroPhysics Suite -- Taller de Procesamiento"
PIPELINE_VERSION = "0.5.0-dev"
DISCOVERY_POLL_MS = 100

logger = logging.getLogger(__name__)


class MainWindow(QMainWindow):
    def __init__(self, *, preferences: AppPreferencesStore | None = None, instrument_profile_store: InstrumentProfileStore | None = None):
        super().__init__()
        self.preferences = preferences or AppPreferencesStore()
        self.instrument_profile_store = instrument_profile_store or InstrumentProfileStore()
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

        self._processes: list[ProcessDefinition] = build_process_registry(profile_store=self.instrument_profile_store)
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
        self._build_toolbar()
        self._build_status_bar()
        self.statusBar().showMessage("Listo")

    # ---------------------------------------------------------------- docks
    def _build_docks(self) -> None:
        self.explorer = ProcessExplorer(self._processes, self)
        self.explorer.process_activated.connect(self._activate_process)
        self.explorer_dock = QDockWidget("EXPLORADOR DE PROCESOS", self)
        self.explorer_dock.setObjectName("ExplorerDock")
        self.explorer_dock.setWidget(self.explorer)
        self.addDockWidget(Qt.DockWidgetArea.LeftDockWidgetArea, self.explorer_dock)

        self.properties = PropertiesDock(self)
        self.properties.run_requested.connect(self._run_process)
        self.properties_dock = QDockWidget("PROPIEDADES", self)
        self.properties_dock.setObjectName("PropertiesDock")
        self.properties_dock.setWidget(self.properties)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.properties_dock)

        self.console = ConsoleDock(self)
        self.console_dock = QDockWidget("CONSOLA", self)
        self.console_dock.setObjectName("ConsoleDock")
        self.console_dock.setWidget(self.console)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.console_dock)

        self.candidates_dock_widget = CandidatesDock(self.session_state, DARK, self)
        self.candidates_dock_widget.candidate_activated.connect(self._open_candidate_detail)
        self.candidates_dock = QDockWidget("CANDIDATOS", self)
        self.candidates_dock.setObjectName("CandidatesDock")
        self.candidates_dock.setWidget(self.candidates_dock_widget)
        self.addDockWidget(Qt.DockWidgetArea.RightDockWidgetArea, self.candidates_dock)
        self.tabifyDockWidget(self.properties_dock, self.candidates_dock)
        self.properties_dock.raise_()

    def _build_status_bar(self) -> None:
        self.readout_label = QLabel("X: --  Y: --  Valor: --")
        """Lectura de píxel bajo el cursor -- estilo PixInsight
        ("Readout"): posición de imagen + valor ADU real, actualizada
        por `_on_pixel_hovered` cada vez que una `ImageView` emite
        `pixel_hovered`. Nunca un valor inventado: `nan` (mostrado como
        "--") si el cursor cae fuera de los límites de la imagen."""
        self.readout_label.setMinimumWidth(260)
        self.statusBar().addPermanentWidget(self.readout_label)

        self.discovery_progress = QProgressBar(self)
        self.discovery_progress.setMaximumWidth(220)
        self.discovery_progress.setVisible(False)
        self.statusBar().addPermanentWidget(self.discovery_progress)

    # ---------------------------------------------------------------- menú
    def _build_menu(self) -> None:
        self.file_menu = self.menuBar().addMenu("&Archivo")
        self.open_action = QAction("&Abrir FITS...", self)
        self.open_action.setShortcut("Ctrl+O")
        self.open_action.triggered.connect(self.open_fits_dialog)
        self.file_menu.addAction(self.open_action)
        self.file_menu.addSeparator()
        self.save_session_action = QAction("&Guardar sesión...", self)
        self.save_session_action.setShortcut("Ctrl+S")
        self.save_session_action.triggered.connect(self._save_session_dialog)
        self.file_menu.addAction(self.save_session_action)
        self.open_session_action = QAction("A&brir sesión...", self)
        self.open_session_action.triggered.connect(self._open_session_dialog)
        self.file_menu.addAction(self.open_session_action)
        self.recent_sessions_menu = self.file_menu.addMenu("Sesiones &recientes")
        self._rebuild_recent_sessions_menu()
        self.file_menu.addSeparator()
        exit_action = QAction("&Salir", self)
        exit_action.setShortcut("Ctrl+Q")
        exit_action.triggered.connect(self.close)
        self.file_menu.addAction(exit_action)

        self.tools_menu = self.menuBar().addMenu("&Herramientas")
        diagnostics_action = QAction("&Diagnóstico de equipo...", self)
        diagnostics_action.triggered.connect(self._open_diagnostics_dialog)
        self.tools_menu.addAction(diagnostics_action)
        arithmetic_action = QAction("&Aritmética entre imágenes...", self)
        arithmetic_action.triggered.connect(self._open_arithmetic_dialog)
        self.tools_menu.addAction(arithmetic_action)
        export_table_action = QAction("&Exportar última tabla a CSV...", self)
        export_table_action.triggered.connect(self._export_last_table)
        self.tools_menu.addAction(export_table_action)

        self.reduction_menu = self.menuBar().addMenu("&Reducción")
        self.build_master_action = QAction("&Construir fotograma maestro...", self)
        self.build_master_action.triggered.connect(self._open_build_master_frame_dialog)
        self.reduction_menu.addAction(self.build_master_action)
        load_master_action = QAction("Cargar fotograma &maestro...", self)
        load_master_action.triggered.connect(self._open_load_master_frame_dialog)
        self.reduction_menu.addAction(load_master_action)
        self.apply_calibration_action = QAction("&Aplicar calibración a la imagen activa...", self)
        self.apply_calibration_action.triggered.connect(self._open_apply_calibration_dialog)
        self.reduction_menu.addAction(self.apply_calibration_action)
        self.reduction_menu.addSeparator()
        reduce_session_action = QAction("Reducir &sesión de LIGHTS...", self)
        reduce_session_action.triggered.connect(self._open_reduce_session_dialog)
        self.reduction_menu.addAction(reduce_session_action)

        self.astrometry_menu = self.menuBar().addMenu("A&strometría")
        self.optical_wcs_action = QAction("WCS desde la &óptica (cámara + focal)...", self)
        self.optical_wcs_action.triggered.connect(self._open_optical_wcs_dialog)
        self.astrometry_menu.addAction(self.optical_wcs_action)
        self.astrometry_menu.addSeparator()
        self.plate_solve_action = QAction("&Resolver placa automáticamente...", self)
        self.plate_solve_action.triggered.connect(self._open_plate_solve_dialog)
        self.astrometry_menu.addAction(self.plate_solve_action)
        self.blind_plate_solve_action = QAction("Resolver placa en &ciego (sin puntero)...", self)
        self.blind_plate_solve_action.triggered.connect(self._open_blind_plate_solve_dialog)
        self.astrometry_menu.addAction(self.blind_plate_solve_action)
        wcs_fit_action = QAction("Ajustar WCS &manualmente (clic + coordenadas)...", self)
        wcs_fit_action.triggered.connect(self._open_wcs_fit_flow)
        self.astrometry_menu.addAction(wcs_fit_action)
        registration_action = QAction("&Registrar por WCS compartido...", self)
        registration_action.triggered.connect(self._open_registration_dialog)
        self.astrometry_menu.addAction(registration_action)
        star_pair_action = QAction("Registrar por &pares de estrellas (clic)...", self)
        star_pair_action.triggered.connect(self._open_star_pair_registration_dialog)
        self.astrometry_menu.addAction(star_pair_action)
        self.astrometry_menu.addSeparator()
        self.catalog_cache_action = QAction("&Descargar catálogo del campo (trabajar sin red)...", self)
        self.catalog_cache_action.triggered.connect(self._open_catalog_cache_dialog)
        self.astrometry_menu.addAction(self.catalog_cache_action)

        self.spectroscopy_menu = self.menuBar().addMenu("Espectroscop&ía")
        wavelength_fit_action = QAction("&Calibrar longitud de onda (detectar líneas)...", self)
        wavelength_fit_action.triggered.connect(self._open_wavelength_fit_flow)
        self.spectroscopy_menu.addAction(wavelength_fit_action)
        combine_spectra_action = QAction("Co&mbinar espectros...", self)
        combine_spectra_action.triggered.connect(self._open_combine_spectra_dialog)
        self.spectroscopy_menu.addAction(combine_spectra_action)
        save_spectrum_action = QAction("&Guardar espectro calibrado (FITS)...", self)
        save_spectrum_action.triggered.connect(self._save_calibrated_spectrum_fits)
        self.spectroscopy_menu.addAction(save_spectrum_action)
        radial_velocity_action = QAction("Medir &velocidad radial...", self)
        radial_velocity_action.triggered.connect(self._open_radial_velocity_dialog)
        self.spectroscopy_menu.addAction(radial_velocity_action)
        synthetic_photometry_action = QAction("Magnitud fotométrica &sintética...", self)
        synthetic_photometry_action.triggered.connect(self._open_synthetic_photometry_dialog)
        self.spectroscopy_menu.addAction(synthetic_photometry_action)
        flux_calibration_action = QAction("Calibración de &flujo absoluta (estrella estándar)...", self)
        flux_calibration_action.triggered.connect(self._open_flux_calibration_dialog)
        self.spectroscopy_menu.addAction(flux_calibration_action)
        flexure_correction_action = QAction("Corrección de fle&xión entre exposiciones...", self)
        flexure_correction_action.triggered.connect(self._open_flexure_correction_dialog)
        self.spectroscopy_menu.addAction(flexure_correction_action)

        telluric_correction_action = QAction("Corrección de absorción &telúrica...", self)
        telluric_correction_action.triggered.connect(self._open_telluric_correction_dialog)
        self.spectroscopy_menu.addAction(telluric_correction_action)
        template_comparison_action = QAction("Comparar con &plantilla de referencia...", self)
        template_comparison_action.triggered.connect(self._open_template_comparison_dialog)
        self.spectroscopy_menu.addAction(template_comparison_action)

        self.view_menu = self.menuBar().addMenu("&Vista")
        self.stf_action = QAction("Alternar STF en la imagen activa", self)
        self.stf_action.setShortcut("Ctrl+T")
        self.stf_action.triggered.connect(self._toggle_active_stf)
        self.view_menu.addAction(self.stf_action)
        self.trace_overlay_lock_action = QAction("Bloquear/desbloquear edición de apertura en la imagen activa (§2)", self)
        self.trace_overlay_lock_action.triggered.connect(self._toggle_active_trace_overlay_lock)
        self.view_menu.addAction(self.trace_overlay_lock_action)

        self.discovery_menu = self.menuBar().addMenu("&Descubrimiento")
        self.new_observation_action = QAction("&Nueva observación...", self)
        self.new_observation_action.setShortcut("Ctrl+N")
        self.new_observation_action.triggered.connect(self._open_new_observation_dialog)
        self.discovery_menu.addAction(self.new_observation_action)
        self.cancel_discovery_action = QAction("&Cancelar análisis", self)
        self.cancel_discovery_action.setEnabled(False)
        self.cancel_discovery_action.triggered.connect(self._cancel_discovery)
        self.discovery_menu.addAction(self.cancel_discovery_action)
        observation_report_action = QAction("Generar informe de &observación...", self)
        observation_report_action.triggered.connect(self._generate_observation_report_dialog)
        self.discovery_menu.addAction(observation_report_action)

        help_menu = self.menuBar().addMenu("A&yuda")
        tutorial_action = QAction("&Tutorial guiado", self)
        tutorial_action.triggered.connect(self._open_tutorial)
        help_menu.addAction(tutorial_action)
        self.tutorial_on_startup_action = QAction("Mostrar tutorial al &iniciar", self)
        self.tutorial_on_startup_action.setCheckable(True)
        self.tutorial_on_startup_action.setChecked(self.preferences.get(_TUTORIAL_SHOW_ON_STARTUP_KEY, "true") == "true")
        self.tutorial_on_startup_action.toggled.connect(self._set_tutorial_show_on_startup)
        help_menu.addAction(self.tutorial_on_startup_action)

    # ---------------------------------------------------------------- barra de herramientas
    def _build_toolbar(self) -> None:
        """Barra de iconos para las acciones más frecuentes -- estilo
        PixInsight (flujo dirigido por barra de herramientas, no solo
        menús). Reutiliza los mismos `QAction` ya creados en
        `_build_menu` (un `QAction` puede estar en un menú y en una
        barra a la vez) -- ningún atajo ni conexión duplicados. Los
        iconos son los pictogramas estándar de Qt/del sistema (nunca un
        diseño propio), y el estilo visual de la barra ya está definido
        en `theme.py` -- este método no toca ni uno ni otro."""
        self.main_toolbar = self.addToolBar("Barra de herramientas principal")
        self.main_toolbar.setObjectName("MainToolbar")
        self.main_toolbar.setMovable(False)
        style = self.style()

        self.open_action.setIcon(style.standardIcon(style.StandardPixmap.SP_DialogOpenButton))
        self.main_toolbar.addAction(self.open_action)
        self.main_toolbar.addSeparator()

        self.new_observation_action.setIcon(style.standardIcon(style.StandardPixmap.SP_FileDialogNewFolder))
        self.main_toolbar.addAction(self.new_observation_action)
        self.cancel_discovery_action.setIcon(style.standardIcon(style.StandardPixmap.SP_DialogCancelButton))
        self.main_toolbar.addAction(self.cancel_discovery_action)
        self.main_toolbar.addSeparator()

        self.plate_solve_action.setIcon(style.standardIcon(style.StandardPixmap.SP_BrowserReload))
        self.main_toolbar.addAction(self.plate_solve_action)
        self.build_master_action.setIcon(style.standardIcon(style.StandardPixmap.SP_DriveHDIcon))
        self.main_toolbar.addAction(self.build_master_action)
        self.apply_calibration_action.setIcon(style.standardIcon(style.StandardPixmap.SP_DialogApplyButton))
        self.main_toolbar.addAction(self.apply_calibration_action)
        self.main_toolbar.addSeparator()

        self.stf_action.setIcon(style.standardIcon(style.StandardPixmap.SP_FileDialogDetailedView))
        self.main_toolbar.addAction(self.stf_action)

        self.toggle_toolbar_action = self.main_toolbar.toggleViewAction()
        self.toggle_toolbar_action.setText("Barra de herramientas principal")
        self.view_menu.addAction(self.toggle_toolbar_action)

    # ---------------------------------------------------------------- imágenes
    def open_fits_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir FITS/XISF", "", "FITS/XISF (*.fits *.fit *.fts *.xisf);;FITS (*.fits *.fit *.fts);;XISF (*.xisf);;Todos los archivos (*.*)")
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
        view.pixel_hovered.connect(self._on_pixel_hovered)
        view.aperture_edited.connect(lambda new_half_width, v=view: self._on_aperture_edited(v, new_half_width))

        sub_window = QMdiSubWindow()
        sub_window.setWidget(view)
        sub_window.setWindowTitle(title)
        sub_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.mdi.addSubWindow(sub_window)
        sub_window.resize(560, 560)
        sub_window.show()

        logger.info("Imagen cargada: %s (%d x %d)", title, data.shape[1], data.shape[0])
        return sub_window

    def _on_pixel_hovered(self, x_px: float, y_px: float, value: float) -> None:
        value_text = f"{value:.2f}" if value == value else "--"  # value == value es False solo para NaN
        self.readout_label.setText(f"X: {x_px:.1f}  Y: {y_px:.1f}  Valor: {value_text}")

    def add_spectrum_window(self, plot_data: SpectrumPlotData, title: str) -> QMdiSubWindow:
        view = SpectrumView(plot_data, title, self.mdi)
        view.point_hovered.connect(self._on_spectrum_point_hovered)

        sub_window = QMdiSubWindow()
        sub_window.setWidget(view)
        sub_window.setWindowTitle(title)
        sub_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.mdi.addSubWindow(sub_window)
        sub_window.resize(640, 420)
        sub_window.show()

        logger.info("Espectro: %s (%d serie(s)) -- rueda para acercar/alejar, arrastrar para desplazar, doble clic para restablecer la vista.", title, len(plot_data.series))
        return sub_window

    def _on_spectrum_point_hovered(self, x: float, y: float, y_error: float, x_label: str, y_label: str) -> None:
        """Lectura en vivo del punto REAL más cercano bajo el cursor
        (§29): píxel o longitud de onda según lo que el proceso haya
        calibrado de verdad (`x_label`), flujo, error real si lo hay, y
        S/N derivada -- nunca fabrica un error o una S/N que el proceso
        de origen no calculó."""
        if x != x:  # NaN fuera del área de la gráfica
            self.readout_label.setText("X: --  Y: --")
            return
        error_text = f"{y_error:.3g}" if y_error == y_error else "N/D"
        snr_text = f"{y / y_error:.1f}" if (y_error == y_error and y_error > 0) else "N/D"
        self.readout_label.setText(f"{x_label}: {x:.3f}  {y_label}: {y:.2f}  Error: {error_text}  S/N: {snr_text}")

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
        dialog.computed.connect(lambda outcome, v=views: self._on_registration_computed(outcome, v))
        dialog.exec()

    def _on_registration_computed(self, outcome: RegistrationOutcome, views: dict[str, ImageView]) -> None:
        self.add_image_window(outcome.data, outcome.title)
        reference_view = views.get(outcome.record.reference_title)
        target_view = views.get(outcome.record.target_title)
        self._offer_to_save_registration_fits(outcome.data, outcome.record, reference_view=reference_view, target_view=target_view)

    def _offer_to_save_registration_fits(
        self, data, record: RegistrationRecord, *, reference_view: ImageView | None, target_view: ImageView | None,
    ) -> None:
        """Ofrece guardar a disco el resultado de "Registrar por WCS
        compartido..." o "Registrar por pares de estrellas...".

        Hallazgo real de la auditoría sistemática del motor de Astrometría/
        WCS (informe 91): de los seis flujos de este menú, estos dos eran
        los únicos que nunca ofrecían guardar su resultado -- las cuatro
        resoluciones de WCS (plate solve, blind solve, ajuste manual,
        óptica) sí lo hacen desde antes vía `_offer_to_save_wcs_fits_copy`.
        Mismo patrón: procedencia real (`build_registration_provenance`/
        `registration_header_cards`), sha256 real de las imágenes de
        origen cuando siguen existiendo, degradación honesta si no.
        """
        from astrophysics_suite.astrometry.provenance import build_registration_provenance, registration_header_cards, strip_wcs_keywords
        from astrophysics_suite.io.fits_reader import sha256_file
        from astrophysics_suite.io.fits_writer import save_fits_image

        input_hashes: list[tuple[str, str]] = []
        for label, view in (("reference", reference_view), ("target", target_view)):
            if view is None or not view.source_path:
                continue
            try:
                input_hashes.append((f"{label}:{Path(view.source_path).name}", sha256_file(view.source_path)))
            except OSError as exc:
                logger.warning("No se pudo calcular el sha256 real de %s para la procedencia: %s", view.source_path, exc)

        provenance = build_registration_provenance(record, input_hashes=tuple(input_hashes))
        question = f"¿Guardar el resultado del registro en un FITS real?\n\n{'; '.join(record.describe())}"
        reply = QMessageBox.question(
            self, "Guardar registro", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        default_path = ""
        if target_view is not None and target_view.source_path:
            source = Path(target_view.source_path)
            default_path = str(source.with_name(f"{source.stem}_registrada{source.suffix}"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar FITS registrado", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return

        # La cabecera de origen real es la del TARGET (los valores de
        # píxel vienen de ahí, solo remuestreados) -- pero su WCS, si
        # tenía uno, ya no describe la rejilla de salida (que ahora es la
        # de la referencia, o ninguna en el caso de pares de estrellas):
        # se elimina explícitamente antes de escribir la procedencia real.
        header = strip_wcs_keywords(target_view.header) if target_view is not None and target_view.header else {}
        header.update(registration_header_cards(record, provenance=provenance))
        try:
            save_fits_image(path, data, header=header)
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar %s: %s", path, exc)
            QMessageBox.critical(self, "Guardar FITS registrado", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("FITS registrado guardado en %s", path)
        self.statusBar().showMessage(f"FITS registrado guardado en {path}", 6000)

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
        worker.finished_ok.connect(lambda result: self._on_star_pair_registration_done(result, reference_view, target_view, reference_title, target_title))
        worker.failed.connect(self._on_process_failed)
        self._active_worker = worker
        worker.finished.connect(lambda: setattr(self, "_active_worker", None))
        worker.start()

    def _on_star_pair_registration_done(
        self, result: tuple, reference_view: ImageView, target_view: ImageView, reference_title: str, target_title: str,
    ) -> None:
        from astrophysics_suite.astrometry.provenance import ENGINE_STAR_PAIR_REGISTRATION

        transform, resampled, model = result
        title = f"{target_title} -> pares con {reference_title}"
        self.add_image_window(resampled, title)
        logger.info(
            "Registro por pares de estrellas: %s -> %s, RMS=%.3f px con %d par(es), modelo=%s",
            target_title, reference_title, transform.rms_residual_px, transform.n_points, model,
        )
        self.statusBar().showMessage(f"Registro por pares completado (RMS={transform.rms_residual_px:.2f} px, {transform.n_points} par(es)).", 6000)
        record = RegistrationRecord(
            engine=ENGINE_STAR_PAIR_REGISTRATION, reference_title=reference_title, target_title=target_title,
            model=model, rms_residual_px=transform.rms_residual_px, n_points=transform.n_points,
        )
        self._offer_to_save_registration_fits(resampled, record, reference_view=reference_view, target_view=target_view)

    def _open_catalog_cache_dialog(self) -> None:
        """Descarga el catálogo del campo a disco -- funciona con o sin
        imagen abierta: con una imagen con WCS, el campo se pre-rellena
        solo; sin ella, se puede indicar el objeto por nombre."""
        from qt_app.catalogs.catalog_cache_dialog import CatalogCacheDialog

        view = self._active_image_view()
        wcs = view.wcs if view is not None else None
        shape = view.data.shape if view is not None else None
        object_name = ""
        if view is not None and view.header:
            object_name = str(view.header.get("OBJECT", "") or "").strip()
        CatalogCacheDialog(wcs, shape, object_name, self).exec()

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
        self._remember_wcs_solution(view, solution)
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table
        logger.info(
            "Placa resuelta automáticamente para %s: RMS=%.3f\" con %d estrella(s).",
            view.title, solution.rms_residual_arcsec, solution.n_stars,
        )
        self.statusBar().showMessage(f"WCS resuelto automáticamente para {view.title} (RMS={solution.rms_residual_arcsec:.3f}\").", 6000)
        self._offer_to_save_wcs_fits_copy(view, dialog.result_record())

    def _open_blind_plate_solve_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de resolver la placa.", 5000)
            return
        dialog = BlindPlateSolveDialog(view.data, view.header, self)
        if dialog.exec() != BlindPlateSolveDialog.DialogCode.Accepted:
            return
        solution = dialog.result_solution()
        if solution is None:
            return
        self._remember_wcs_solution(view, solution)
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table
        logger.info(
            "Placa resuelta en ciego (sin puntero) para %s: RMS=%.3f\" con %d estrella(s).",
            view.title, solution.rms_residual_arcsec, solution.n_stars,
        )
        self.statusBar().showMessage(f"WCS resuelto en ciego para {view.title} (RMS={solution.rms_residual_arcsec:.3f}\").", 6000)
        self._offer_to_save_wcs_fits_copy(view, dialog.result_record())

    def _offer_to_save_wcs_fits_copy(self, view: ImageView, record) -> None:
        """Ofrece guardar una copia del FITS con el WCS en la cabecera.

        `record` es un `WCSRecord`: la solución MÁS el motor que la
        produjo. Antes aquí llegaba solo el `WCSSolution` y esta función
        escribía a mano `HISTORY = "WCS ajustado ... (astrometry.wcs_fit)"`
        pasara lo que pasara -- una placa resuelta en ciego acababa
        declarando en el archivo un motor que no la había resuelto. Las
        tarjetas las construye ahora `astrometry/provenance.py`, en la
        capa de ciencia, donde se pueden probar sin Qt.
        """
        from astrophysics_suite.astrometry.provenance import (
            build_wcs_provenance,
            strip_wcs_keywords,
            wcs_header_cards,
        )
        from astrophysics_suite.io.fits_reader import sha256_file
        from astrophysics_suite.io.fits_writer import save_fits_image

        # sha256 real de la imagen que se resolvió, si se conoce su
        # archivo de origen (informes 52/53/54: input_hashes sin
        # rellenar) -- una imagen derivada sin `source_path` real (p. ej.
        # combinada en memoria) no tiene un archivo que hashear, y no se
        # inventa uno. `source_path` puede apuntar a un archivo que ya no
        # existe (movido/borrado desde que se cargó, o solo un nombre
        # nominal sin fichero real detrás) -- un fallo al releerlo aquí
        # nunca debe impedir guardar la copia con WCS en sí.
        input_hashes: tuple[tuple[str, str], ...] = ()
        if view.source_path:
            try:
                input_hashes = ((f"image:{Path(view.source_path).name}", sha256_file(view.source_path)),)
            except OSError as exc:
                logger.warning("No se pudo calcular el sha256 real de %s para la procedencia: %s", view.source_path, exc)
        provenance = build_wcs_provenance(record, input_hashes=input_hashes)
        detail = (
            f"RMS={record.solution.rms_residual_arcsec:.4f}\" con {record.solution.n_stars} estrella(s)"
            if record.is_measured
            else "solución declarada desde la óptica, sin error medido"
        )
        question = f"¿Guardar una copia del FITS con el WCS escrito en la cabecera?\n\n{detail}"
        if provenance.warnings:
            question += "\n\n" + "\n".join(f"· {w}" for w in provenance.warnings)
        reply = QMessageBox.question(
            self, "Guardar copia con WCS", question,
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

        # Primero se borra el WCS ANTERIOR entero (ver
        # `strip_wcs_keywords`): la cabecera cruda de una cámara ya
        # resuelta trae coeficientes SIP que sobreviven a sobrescribir
        # CRVAL/CRPIX/CD y falsean la solución nueva en los bordes.
        header = strip_wcs_keywords(view.header) if view.header else {}
        header.update(wcs_header_cards(record, provenance=provenance))
        try:
            save_fits_image(path, view.data, header=header)
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar %s: %s", path, exc)
            QMessageBox.critical(self, "Guardar FITS con WCS", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("FITS con WCS (%s) guardado en %s", record.source, path)
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

    def _remember_wcs_solution(self, view: ImageView, solution) -> None:
        """Deja el `WCSSolution` real en la vista (comportamiento ya
        existente, p. ej. para "Registrar por WCS compartido...") Y en
        `SessionState` (nuevo), indexado por la ruta real de la imagen --
        para que "Generar informe científico..." pueda mostrar
        residuales astrométricos reales en vez de NO DISPONIBLE cuando
        el candidato viene de esta misma imagen, mientras la sesión de
        GUI siga abierta."""
        view.fitted_wcs_solution = solution
        if view.source_path:
            self.session_state.set_wcs_solution(view.source_path, solution)

    def _open_optical_wcs_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de construir su WCS desde la óptica.", 5000)
            return
        dialog = OpticalWCSDialog(view.data.shape, view.header, self)
        dialog.built.connect(lambda solution, setup, v=view: self._on_optical_wcs_built(v, solution, setup))
        dialog.exec()

    def _on_optical_wcs_built(self, view: ImageView, solution, setup) -> None:
        self._remember_wcs_solution(view, solution)
        width_deg, height_deg = setup.field_of_view_deg
        logger.info(
            "WCS construido desde la óptica para %s: %s a %.0f mm -> %.4f \"/px, campo %.1f' x %.1f'. "
            "Solución declarada por el usuario (sin ajuste contra estrellas), centrada en RA=%.6f° Dec=%.6f°.",
            view.title, setup.camera_name, setup.focal_length_mm, setup.pixel_scale_arcsec,
            width_deg * 60, height_deg * 60, solution.crval_deg[0], solution.crval_deg[1],
        )
        self.statusBar().showMessage(
            f"WCS desde la óptica para {view.title}: {setup.pixel_scale_arcsec:.4f}\"/px, "
            f"campo {width_deg * 60:.1f}' × {height_deg * 60:.1f}'.", 8000
        )
        self._offer_to_save_wcs_fits_copy(
            view,
            WCSRecord(
                solution=solution, source=SOURCE_OPTICS,
                optics_description=f"{setup.camera_name} ({setup.pixel_size_um:g} um) a {setup.focal_length_mm:g} mm",
            ),
        )

    def _on_wcs_fitted(self, view: ImageView, solution, table: Table) -> None:
        self._remember_wcs_solution(view, solution)
        self._last_result_table = table
        logger.info(
            "WCS ajustado para %s: RMS=%.3f\" con %d estrella(s). Tabla disponible -- Herramientas -> Exportar última tabla a CSV...",
            view.title, solution.rms_residual_arcsec, solution.n_stars,
        )
        self.statusBar().showMessage(f"WCS ajustado para {view.title} (RMS={solution.rms_residual_arcsec:.3f}\").", 6000)
        # Un ajuste manual se perdía al cerrar el programa: solo las dos
        # resoluciones automáticas ofrecían guardar la copia con WCS.
        self._offer_to_save_wcs_fits_copy(view, WCSRecord(solution=solution, source=SOURCE_MANUAL_FIT))

    def _save_session_dialog(self) -> None:
        from astrophysics_suite.io.session_export import save_session

        if not self.session_state.candidates and not self.session_state.observations:
            self.statusBar().showMessage("No hay ninguna observación ni candidato que guardar todavía -- ejecuta un análisis de Descubrimiento primero.", 6000)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Guardar sesión", "", "Sesión AstroPhysics Suite (*.apssession.json)")
        if not path:
            return
        try:
            save_session(
                path, project_name=self.session_state.project_name,
                observations=self.session_state.observations, candidates=self.session_state.candidates,
                # las calibraciones por imagen ya no mueren al cerrar:
                # un WCS ajustado a mano o construido desde la óptica, y
                # el punto cero real, viajan con la sesión.
                wcs_solutions=self.session_state.wcs_solutions,
                zeropoint_fits=self.session_state.zeropoint_fits,
            )
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar la sesión en %s: %s", path, exc)
            QMessageBox.critical(self, "Guardar sesión", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("Sesión guardada en %s (%d candidato(s), %d observación/es)", path, len(self.session_state.candidates), len(self.session_state.observations))
        self.statusBar().showMessage(f"Sesión guardada en {path}", 6000)
        self._remember_recent_session(path)

    def _open_session_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Abrir sesión", "", "Sesión AstroPhysics Suite (*.apssession.json);;JSON (*.json);;Todos los archivos (*.*)")
        if not path:
            return
        self._open_session_from_path(path)

    def _open_session_from_path(self, path: str) -> None:
        from astrophysics_suite.io.session_export import load_session

        try:
            loaded = load_session(path)
        except Exception as exc:  # noqa: BLE001 -- error real de lectura, debe ser visible
            logger.error("No se pudo abrir la sesión %s: %s", path, exc)
            QMessageBox.critical(self, "Abrir sesión", f"No se pudo abrir «{Path(path).name}»:\n\n{exc}")
            return
        self.session_state.load_saved_session(
            project_name=loaded.project_name, observations=list(loaded.observations), candidates=list(loaded.candidates),
        )
        for image_path, solution in loaded.wcs_solutions.items():
            self.session_state.set_wcs_solution(image_path, solution)
        for image_path, fit in loaded.zeropoint_fits.items():
            self.session_state.set_zeropoint_fit(image_path, fit)
        logger.info(
            "Sesión abierta desde %s (%d candidato(s), %d observación/es, %d WCS, %d punto(s) cero)",
            path, len(loaded.candidates), len(loaded.observations), len(loaded.wcs_solutions), len(loaded.zeropoint_fits),
        )
        self.statusBar().showMessage(f"Sesión abierta desde {path}: {len(loaded.candidates)} candidato(s) añadidos", 6000)
        self._remember_recent_session(path)

    def _recent_sessions(self) -> list[str]:
        raw = self.preferences.get(_RECENT_SESSIONS_PREFERENCE_KEY, "")
        if not raw:
            return []
        try:
            paths = json.loads(raw)
        except json.JSONDecodeError:
            return []
        return [p for p in paths if isinstance(p, str)]

    def _remember_recent_session(self, path: str) -> None:
        recent = [p for p in self._recent_sessions() if p != path]
        recent.insert(0, path)
        self.preferences.set(_RECENT_SESSIONS_PREFERENCE_KEY, json.dumps(recent[:_MAX_RECENT_SESSIONS]))
        self._rebuild_recent_sessions_menu()

    def _rebuild_recent_sessions_menu(self) -> None:
        self.recent_sessions_menu.clear()
        recent = self._recent_sessions()
        if not recent:
            empty_action = QAction("(ninguna todavía)", self)
            empty_action.setEnabled(False)
            self.recent_sessions_menu.addAction(empty_action)
            return
        for path in recent:
            action = QAction(Path(path).name, self)
            action.setToolTip(path)
            action.triggered.connect(lambda checked=False, p=path: self._open_session_from_path(p))
            self.recent_sessions_menu.addAction(action)

    def _export_last_table(self) -> None:
        if self._last_result_table is None:
            self.statusBar().showMessage("No hay ninguna tabla que exportar todavía -- ejecuta un proceso que produzca una (p. ej. punto cero, ajuste de WCS).", 6000)
            return
        path, _ = QFileDialog.getSaveFileName(self, "Exportar tabla a CSV", "", "CSV (*.csv)")
        if not path:
            return
        self._last_result_table.to_csv(path)
        self.statusBar().showMessage(f"Tabla exportada a {path}", 5000)

    def _generate_observation_report_dialog(self) -> None:
        from astrophysics_suite.export.html import export_html
        from astrophysics_suite.reporting.observation_report import build_observation_report

        if not self.session_state.observations:
            self.statusBar().showMessage("No hay ninguna observación todavía -- ejecuta un análisis de Descubrimiento primero.", 6000)
            return
        if len(self.session_state.observations) == 1:
            observation = self.session_state.observations[0]
        else:
            labels = [f"{o.target_name} ({o.observation_id})" for o in self.session_state.observations]
            choice, ok = QInputDialog.getItem(self, "Generar informe de observación", "Observación:", labels, len(labels) - 1, editable=False)
            if not ok:
                return
            observation = self.session_state.observations[labels.index(choice)]

        candidates = [c for c in self.session_state.candidates if c.observation_id == observation.observation_id]
        path, _ = QFileDialog.getSaveFileName(self, "Generar informe de observación", f"{observation.observation_id}.html", "HTML (*.html)")
        if not path:
            return
        try:
            report = build_observation_report(observation, candidates, pipeline_version=observation.observation_id)
            export_html(report, path)
        except Exception as exc:  # noqa: BLE001 -- error real de generación/escritura, debe ser visible
            logger.error("No se pudo generar el informe de observación %s en %s: %s", observation.observation_id, path, exc)
            QMessageBox.critical(self, "Generar informe de observación", f"No se pudo generar el informe en «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("Informe de observación %s generado en %s (%d candidato(s))", observation.observation_id, path, len(candidates))
        self.statusBar().showMessage(f"Informe de observación generado en {path}", 6000)

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

        dialog = WavelengthFitDialog(lines, self, spectrum=spectrum)
        dialog.fitted.connect(
            lambda solution, table, record, v=view, s=spectrum: self._on_wavelength_fitted(v, solution, table, record, s)
        )
        dialog.exec()

    def _on_wavelength_fitted(self, view: ImageView, solution, table: Table, record=None, spectrum=None) -> None:
        view.fitted_wavelength_solution = solution
        view.wavelength_calibration_record = record
        view.wavelength_calibration_spectrum = spectrum
        self._last_result_table = table
        logger.info(
            "Longitud de onda calibrada para %s: RMS=%.4f (grado %d, %d línea(s)). Tabla disponible -- Herramientas -> Exportar última tabla a CSV...",
            view.title, solution.rms_residual, solution.degree, len(table.rows),
        )
        status_text = f"Longitud de onda calibrada para {view.title} (RMS={solution.rms_residual:.4f})."
        # §11: los avisos honestos reales que ya calcula `build_wavelength_
        # provenance` (SIMULADA, estrella de referencia, pocas líneas para
        # el grado...) se enviaban al FITS de salida pero nunca se
        # mostraban aquí -- un usuario que calibra desde la GUI y nunca
        # guarda el archivo no llegaba a verlos.
        if record is not None:
            provenance = build_wavelength_provenance(record)
            for warning in provenance.warnings:
                logger.warning("[Calibrar longitud de onda] AVISO: %s", warning)
            if provenance.warnings:
                status_text += f" -- {len(provenance.warnings)} aviso(s), ver registro de operaciones."
        self.statusBar().showMessage(status_text, 6000)

    def _save_calibrated_spectrum_fits(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de guardar un espectro calibrado.", 5000)
            return
        if view.wavelength_calibration_record is None or view.wavelength_calibration_spectrum is None:
            self.statusBar().showMessage(
                f"{view.title} no tiene una calibración en longitud de onda ajustada todavía -- "
                "usa antes \"Calibrar longitud de onda...\".", 7000,
            )
            return

        from astrophysics_suite.spectroscopy.spectrum1d_io import processing_history_path_for_product, save_spectrum1d_fits, standard_product_name

        object_name = (view.header or {}).get("OBJECT")
        default_name = standard_product_name(object_name, view.source_path)  # §37: nombre de producto estándar
        default_path = str(Path(view.source_path).with_name(default_name)) if view.source_path else default_name
        path, _ = QFileDialog.getSaveFileName(self, "Guardar espectro calibrado", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return
        try:
            save_spectrum1d_fits(
                path, view.wavelength_calibration_spectrum, view.wavelength_calibration_record,
                header=dict(view.header) if view.header else None,
            )
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar el espectro calibrado de %s en %s: %s", view.title, path, exc)
            QMessageBox.critical(self, "Guardar espectro calibrado", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("Espectro calibrado de %s guardado en %s (%s)", view.title, path, view.wavelength_calibration_record.source.value)

        # §36/§39: junto al producto, el historial real de TODO lo que se
        # aplicó sobre esta vista (nunca solo el último paso) -- por
        # APPEND (`append_processing_history`), así que guardar el mismo
        # producto varias veces nunca pierde la cadena ya registrada.
        view.processing_history.append(
            ProcessingHistoryEntry(
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                process_name="Guardar espectro calibrado (FITS)",
                summary=f"Guardado en {path} ({view.wavelength_calibration_record.source.value}).",
            )
        )
        history_path = processing_history_path_for_product(path)
        try:
            append_processing_history(history_path, tuple(view.processing_history))
        except Exception as exc:  # noqa: BLE001 -- error real de escritura del historial, no debe silenciarse
            logger.error("No se pudo escribir el historial de procesamiento en %s: %s", history_path, exc)
        self.statusBar().showMessage(f"Espectro calibrado guardado en {path}", 6000)

    def _open_radial_velocity_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de medir velocidad radial.", 5000)
            return
        if view.fitted_wavelength_solution is None:
            self.statusBar().showMessage(
                f"{view.title} no tiene una calibración en longitud de onda ajustada todavía -- "
                "usa antes \"Calibrar longitud de onda...\".", 7000,
            )
            return
        dialog = RadialVelocityDialog(view, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_synthetic_photometry_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de calcular una magnitud fotométrica.", 5000)
            return
        if view.fitted_wavelength_solution is None:
            self.statusBar().showMessage(
                f"{view.title} no tiene una calibración en longitud de onda ajustada todavía -- "
                "usa antes \"Calibrar longitud de onda...\".", 7000,
            )
            return
        dialog = SyntheticPhotometryDialog(view, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_flux_calibration_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage(
                "Abre al menos dos ventanas (estrella estándar + científica) antes de calibrar el flujo.", 5000
            )
            return
        dialog = FluxCalibrationDialog(views, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_flexure_correction_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage(
                "Abre al menos dos ventanas (referencia + nueva exposición) antes de corregir la flexión.", 5000
            )
            return
        dialog = FlexureCorrectionDialog(views, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_telluric_correction_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage(
                "Abre al menos dos ventanas (estándar telúrica + científica) antes de corregir telúricas.", 5000
            )
            return
        dialog = TelluricCorrectionDialog(views, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_template_comparison_dialog(self) -> None:
        views = self._image_views_by_title()
        if not views:
            self.statusBar().showMessage("Abre una imagen ya calibrada en longitud de onda antes de comparar con una plantilla.", 5000)
            return
        dialog = TemplateComparisonDialog(views, self)
        dialog.exec()
        table = dialog.result_table()
        if table is not None:
            self._last_result_table = table

    def _open_combine_spectra_dialog(self) -> None:
        views = self._image_views_by_title()
        if len(views) < 2:
            self.statusBar().showMessage("Abre al menos dos imágenes antes de combinar espectros.", 5000)
            return
        dialog = CombineSpectraDialog(views, self)
        dialog.combined.connect(self._on_spectra_combined)
        dialog.exec()

    def _on_spectra_combined(self, result, table: Table) -> None:
        self._last_result_table = table
        n_valid = int(np.count_nonzero(~np.isnan(result.flux)))
        wavelength_unit = table.units[0] if table.units else ""
        x_label = f"Longitud de onda ({wavelength_unit})" if wavelength_unit else "Longitud de onda"
        # el visor real respeta los NaN de puntos sin cobertura como
        # huecos reales en el trazo -- nunca se rellenan con un valor
        # inventado solo para poder dibujar algo.
        plot_data = SpectrumPlotData(
            series=(SpectrumSeries(label=f"Combinado ({result.method})", x=result.wavelength, y=result.flux),),
            x_label=x_label, y_label="Flujo (ADU)",
        )
        title = f"Espectro combinado ({result.method}, {n_valid}/{result.wavelength.size} pts)"
        self.add_spectrum_window(plot_data, title)
        logger.info(
            "Espectro combinado (%s): %d/%d punto(s) con dato real. Tabla disponible -- Herramientas -> Exportar última tabla a CSV...",
            result.method, n_valid, result.wavelength.size,
        )
        self.statusBar().showMessage(f"Espectro combinado ({result.method}) -- {n_valid}/{result.wavelength.size} puntos con dato real.", 6000)

    def _open_build_master_frame_dialog(self) -> None:
        dialog = BuildMasterFrameDialog(self.master_frame_library, self, preferences=self.preferences)
        if dialog.exec() == BuildMasterFrameDialog.DialogCode.Accepted:
            logger.info("Fotograma maestro construido: %s", dialog.name_edit.text().strip())

    def _open_load_master_frame_dialog(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Cargar fotograma maestro", "", "FITS (*.fits *.fit *.fts)")
        if not path:
            return
        from astrophysics_suite.reduction.master_frames import load_master_frame

        try:
            master_frame = load_master_frame(path)
        except (ValueError, OSError) as exc:
            QMessageBox.critical(
                self, "Cargar fotograma maestro",
                f"No se pudo cargar «{Path(path).name}» como fotograma maestro:\n\n{exc}",
            )
            return

        default_name = Path(path).stem
        existing_names = self.master_frame_library.all_names()
        proposed_name = default_name
        suffix = 2
        while proposed_name in existing_names:
            proposed_name = f"{default_name} ({suffix})"
            suffix += 1
        name, ok = QInputDialog.getText(self, "Cargar fotograma maestro", "Nombre para esta entrada en la biblioteca:", text=proposed_name)
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in existing_names:
            QMessageBox.warning(self, "Cargar fotograma maestro", "Ya existe un fotograma maestro con ese nombre.")
            return

        saved_at = datetime.fromtimestamp(Path(path).stat().st_mtime, tz=timezone.utc)
        self.master_frame_library.add(name, master_frame, path=path, saved_at=saved_at)
        logger.info("Fotograma maestro cargado desde %s como «%s» (%s)", path, name, master_frame.kind)
        self.statusBar().showMessage(f"Fotograma maestro «{name}» cargado desde {path}.", 6000)

    def _open_apply_calibration_dialog(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("Abre o selecciona una imagen antes de calibrar.", 5000)
            return
        if len(self.master_frame_library) == 0:
            self.statusBar().showMessage("Construye al menos un fotograma maestro antes de calibrar.", 5000)
            return
        dialog = ApplyCalibrationDialog(self.master_frame_library, view.data, self)
        dialog.calibrated.connect(lambda outcome, v=view: self._on_calibration_applied(v, outcome))
        dialog.exec()

    def _on_calibration_applied(self, view: ImageView, outcome: CalibrationOutcome) -> None:
        logger.info("Calibración aplicada a %s: %s", view.title, outcome.summary)
        self.add_image_window(outcome.image.data, f"{view.title} -> calibrada")
        self._offer_to_save_calibrated_fits(view, outcome)

    def _offer_to_save_calibrated_fits(self, view: ImageView, outcome: CalibrationOutcome) -> None:
        """Ofrece guardar a disco el resultado de "Aplicar calibración...".

        Hallazgo real de la auditoría sistemática del motor de Reducción
        (informe 90): a diferencia de "Reducir sesión de LIGHTS...", que
        escribe cada calibrado a un FITS real desde su primera versión,
        este flujo de una sola imagen dejaba el resultado únicamente en
        una ventana MDI en memoria -- sin ninguna forma de persistirlo,
        con procedencia o sin ella. Reutiliza exactamente el mismo patrón
        que `_offer_to_save_wcs_fits_copy`: procedencia real con
        `reduction_header_cards`/`build_reduction_provenance` (las mismas
        que ya usa `ReduceSessionDialog`), sha256 real de la imagen de
        origen solo si `source_path` sigue apuntando a un archivo real, y
        selector de guardado nativo (nunca una ruta inventada).
        """
        from astrophysics_suite.io.fits_reader import sha256_file
        from astrophysics_suite.io.fits_writer import save_fits_image
        from astrophysics_suite.reduction.provenance import build_reduction_provenance, reduction_header_cards

        input_hashes = outcome.master_input_hashes
        if view.source_path:
            try:
                input_hashes = ((f"light:{Path(view.source_path).name}", sha256_file(view.source_path)),) + input_hashes
            except OSError as exc:
                logger.warning("No se pudo calcular el sha256 real de %s para la procedencia: %s", view.source_path, exc)

        provenance = build_reduction_provenance(outcome.record, input_hashes=input_hashes)
        question = f"¿Guardar el resultado de la calibración en un FITS real?\n\n{outcome.summary}"
        if provenance.warnings:
            question += "\n\n" + "\n".join(f"· {w}" for w in provenance.warnings)
        reply = QMessageBox.question(
            self, "Guardar calibración", question,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.Yes,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        default_path = ""
        if view.source_path:
            source = Path(view.source_path)
            default_path = str(source.with_name(f"{source.stem}_calibrada{source.suffix}"))
        path, _ = QFileDialog.getSaveFileName(self, "Guardar FITS calibrado", default_path, "FITS (*.fits *.fit *.fts)")
        if not path:
            return

        header = dict(view.header) if view.header else {}
        header.update(reduction_header_cards(outcome.record, provenance=provenance))
        try:
            save_fits_image(path, outcome.image.data, header=header, uncertainty=outcome.image.uncertainty)
        except Exception as exc:  # noqa: BLE001 -- error real de escritura, debe ser visible
            logger.error("No se pudo guardar %s: %s", path, exc)
            QMessageBox.critical(self, "Guardar FITS calibrado", f"No se pudo guardar «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("FITS calibrado guardado en %s", path)
        self.statusBar().showMessage(f"FITS calibrado guardado en {path}", 6000)

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

        if process.process_id == "spectroscopy.multiaperture":
            centers = find_aperture_centers(
                view.data,
                min_snr=float(params.get("min_snr", 5.0)),
                min_separation_px=float(params.get("min_separation_px", 10.0)),
                max_apertures=int(params.get("max_apertures", 20)),
            )
            if not centers:
                self.statusBar().showMessage(
                    "Detección automática: no se encontró ningún objeto en el perfil espacial -- baja la S/N mínima o marca las posiciones a mano.",
                    6000,
                )
                return
            points = [(0.0, c) for c in centers]
            message = f"Detección automática (perfil espacial): {len(points)} apertura(s) encontrada(s)."
        elif process.process_id == "photometry.psf":
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
        params["_header"] = view.header
        params["_wavelength_solution"] = view.fitted_wavelength_solution
        params["_instrument_profiles"] = self.instrument_profile_store.load_all()

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
        view.processing_history.append(
            ProcessingHistoryEntry(
                timestamp_utc=datetime.now(timezone.utc).isoformat(), process_name=process.name, summary=result.summary,
            )
        )
        spectrum = result.artifacts.get("spectrum")
        if spectrum is not None:
            self.add_spectrum_window(spectrum, f"{view.title} -> {process.name}")
        elif result.output_data is not None:
            self.add_image_window(result.output_data, f"{view.title} -> {process.name}")
        trace_overlay = result.artifacts.get("trace_overlay")
        if trace_overlay is not None:
            view.set_trace_overlay(trace_overlay)
        # §2: solo editable cuando hay UNA traza real (no multi-apertura/
        # objeto extendido, que producen varias a la vez) -- una traza
        # nueva reemplaza cualquier contexto de edición anterior, nunca
        # lo deja apuntando a una apertura que ya no está dibujada.
        view.trace_edit_context = result.artifacts.get("trace_edit_context")
        if result.table is not None:
            self._last_result_table = result.table
            logger.info("    Tabla disponible (%d fila(s)) -- Herramientas -> Exportar última tabla a CSV...", len(result.table.rows))
        zeropoint_fit = result.artifacts.get("zeropoint_fit")
        if zeropoint_fit is not None and view.source_path:
            self.session_state.set_zeropoint_fit(view.source_path, zeropoint_fit)
        wavelength_calibration_record = result.artifacts.get("wavelength_calibration_record")
        if wavelength_calibration_record is not None:
            view.fitted_wavelength_solution = wavelength_calibration_record.solution
            view.wavelength_calibration_record = wavelength_calibration_record
            view.wavelength_calibration_spectrum = result.artifacts.get("wavelength_calibration_spectrum")

    def _on_process_failed(self, message: str) -> None:
        self.properties.apply_button.setEnabled(True)
        self.statusBar().showMessage("Error al ejecutar el proceso", 5000)
        logger.error("%s", message)

    def _on_aperture_edited(self, view: ImageView, new_aperture_half_width: float) -> None:
        """§2: tras arrastrar el borde de la apertura sobre el overlay
        real, recalcula la extracción con la MISMA traza ya conocida
        (`view.trace_edit_context`) -- nunca retraza ni pide un nuevo
        clic. Abre el resultado como una ventana de espectro nueva, igual
        que ya hace cualquier extracción, y lo deja en el historial de
        procesamiento real de la vista (§36)."""
        context = view.trace_edit_context
        if context is None:
            return
        try:
            spectrum = recalculate_extraction(context, new_aperture_half_width)
        except ValueError as exc:
            self.statusBar().showMessage(f"No se pudo recalcular la extracción: {exc}", 6000)
            return

        pixel = np.arange(spectrum.flux.size, dtype=np.float64)
        plot_data = SpectrumPlotData(
            series=(SpectrumSeries(label="Flujo extraído (recalculado)", x=pixel, y=spectrum.flux, y_error=spectrum.flux_uncertainty),),
            x_label="Píxel (dispersión)", y_label="Flujo extraído (ADU)",
        )
        title = f"{view.title} -> Extracción recalculada (apertura={new_aperture_half_width:.1f} px)"
        self.add_spectrum_window(plot_data, title)

        summary = f"Apertura recalculada a {new_aperture_half_width:.2f} px por arrastre real del overlay ({context.extraction_method_label})."
        view.processing_history.append(
            ProcessingHistoryEntry(
                timestamp_utc=datetime.now(timezone.utc).isoformat(),
                process_name="Recalcular extracción (edición de apertura, §2)", summary=summary,
            )
        )
        logger.info("[Recalcular extracción] %s", summary)
        self.statusBar().showMessage(summary, 6000)

    def _toggle_active_trace_overlay_lock(self) -> None:
        view = self._active_image_view()
        if view is None:
            self.statusBar().showMessage("No hay ninguna imagen activa.", 4000)
            return
        view.trace_overlay_locked = not view.trace_overlay_locked
        state = "bloqueada" if view.trace_overlay_locked else "desbloqueada"
        self.statusBar().showMessage(f"Edición de apertura {state} en {view.title}.", 4000)

    # ---------------------------------------------------------------- descubrimiento
    def _open_new_observation_dialog(self) -> None:
        if self._discovery_job is not None:
            self.statusBar().showMessage("Ya hay un análisis en curso; espera a que termine.", 5000)
            return
        dialog = NewObservationDialog(self)
        if dialog.exec() != NewObservationDialog.DialogCode.Accepted:
            return
        self._start_discovery(dialog.result_target_name(), dialog.result_images(), dialog.result_auto_plate_solve())

    def _start_discovery(self, target_name: str, images: list[tuple[str, str]], auto_plate_solve: bool = True) -> None:
        self._discovery_job = DiscoveryJob(
            target_name=target_name,
            images=images,
            params=DiscoveryParams(auto_plate_solve=auto_plate_solve),
            pipeline_version=PIPELINE_VERSION,
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
                n_auto_resolved = 0
                n_blind_resolved = 0
                n_wcs_missing = 0
                for wcs_status in event.summary.wcs_status:
                    logger.info("WCS %s (%s): %s", wcs_status.state, wcs_status.band, wcs_status.detail)
                    if wcs_status.state == WCS_STATE_AUTO_RESOLVED:
                        n_auto_resolved += 1
                    elif wcs_status.state == WCS_STATE_BLIND_RESOLVED:
                        n_blind_resolved += 1
                    elif wcs_status.state in (WCS_STATE_SOLVE_FAILED, WCS_STATE_SOLVE_NOT_RUN):
                        n_wcs_missing += 1
                wcs_suffix = ""
                if n_auto_resolved or n_blind_resolved or n_wcs_missing:
                    wcs_suffix = (
                        f" WCS: {n_auto_resolved} resuelto(s) con puntero, {n_blind_resolved} resuelto(s) en ciego, "
                        f"{n_wcs_missing} sin WCS (ver consola)."
                    )
                self.statusBar().showMessage(
                    f"Completado: {event.summary.n_candidates} candidatos de {event.summary.n_detected} detecciones.{wcs_suffix}", 8000
                )
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

        widget = CandidateDetailWidget(candidate_id, self.session_state, DARK, self, preferences=self.preferences)
        widget.report_generated.connect(lambda path: self.statusBar().showMessage(f"Informe científico generado en {path}", 6000))
        sub_window = QMdiSubWindow()
        sub_window.setWidget(widget)
        sub_window.setWindowTitle(f"Candidato: {candidate_id}")
        sub_window.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose)
        self.mdi.addSubWindow(sub_window)
        sub_window.resize(560, 680)
        sub_window.show()

        self._candidate_detail_windows[candidate_id] = sub_window
        sub_window.destroyed.connect(lambda: self._candidate_detail_windows.pop(candidate_id, None))

    # ---------------------------------------------------------------- tutorial guiado
    def maybe_show_tutorial_on_startup(self) -> None:
        """Llamado por el punto de entrada real (`qt_app/__main__.py`)
        tras `show()` -- nunca desde `__init__`, para que construir un
        `MainWindow` (como hacen todas las pruebas) nunca dispare por sí
        solo una ventana emergente. Aparece la primera vez (preferencia
        sin fijar todavía) y deja de aparecer en cuanto el tutorial se
        completa o se salta, hasta que el usuario reactive "Mostrar
        tutorial al iniciar"."""
        if self.preferences.get(_TUTORIAL_SHOW_ON_STARTUP_KEY, "true") == "true":
            self._open_tutorial()

    def _open_tutorial(self) -> None:
        overlay = TutorialOverlay(self, build_tutorial_steps(), on_finished=self._on_tutorial_finished)
        overlay.setGeometry(self.rect())
        overlay.show()
        overlay.raise_()

    def _on_tutorial_finished(self) -> None:
        self.preferences.set(_TUTORIAL_SHOW_ON_STARTUP_KEY, "false")
        self.tutorial_on_startup_action.blockSignals(True)
        self.tutorial_on_startup_action.setChecked(False)
        self.tutorial_on_startup_action.blockSignals(False)

    def _set_tutorial_show_on_startup(self, checked: bool) -> None:
        self.preferences.set(_TUTORIAL_SHOW_ON_STARTUP_KEY, "true" if checked else "false")
