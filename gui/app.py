"""Ventana principal: barra lateral de navegación + área de contenido.
Orquesta las vistas y los servicios (`services/`) -- nunca contiene
lógica científica (ver docs/audit/10-FASE8-GUI.md).
"""
from __future__ import annotations

import tkinter as tk

from services.discovery_service import DiscoveryJob
from services.logging_bridge import GuiLogBridge
from services.session_state import SessionState

from gui.theme import DARK, LIGHT, apply_theme
from gui.views.analysis_view import AnalysisView
from gui.views.candidate_detail_view import CandidateDetailView
from gui.views.candidates_view import CandidatesView
from gui.views.diagnostics_view import DiagnosticsView
from gui.views.new_observation_view import NewObservationView
from gui.views.project_view import ProjectView
from gui.views.settings_view import SettingsView

APP_TITLE = "AstroPhysics Suite"
PIPELINE_VERSION = "0.4.0-dev"

NAV_ITEMS = [
    ("project", "Proyecto"),
    ("new_observation", "Nueva observación"),
    ("candidates", "Candidatos"),
    ("settings", "Configuración avanzada"),
    ("diagnostics", "Diagnóstico"),
]


class App:
    def __init__(self, root: tk.Tk, *, dark: bool = False):
        self.root = root
        self.palette = DARK if dark else LIGHT
        self.fonts = apply_theme(root, self.palette)
        self.state = SessionState()
        self.log_bridge = GuiLogBridge()
        self.log_bridge.attach()

        self.active_job: DiscoveryJob | None = None
        self.selected_candidate_id: str | None = None
        self.pending_analysis: dict | None = None
        """Parámetros de la última "Nueva observación" enviados, para que
        la vista de Análisis sepa qué job lanzar al mostrarse."""

        root.title(APP_TITLE)
        root.geometry("1280x820")
        root.minsize(1040, 640)
        root.configure(background=self.palette.bg)

        self._build_layout()
        self.show_view("project")

    # ---------------------------------------------------------------- layout
    def _build_layout(self) -> None:
        container = tk.Frame(self.root, background=self.palette.bg)
        container.pack(fill="both", expand=True)

        self.sidebar = tk.Frame(container, background=self.palette.bg_hero, width=228)
        self.sidebar.pack(side="left", fill="y")
        self.sidebar.pack_propagate(False)

        brand = tk.Frame(self.sidebar, background=self.palette.bg_hero)
        brand.pack(fill="x", padx=20, pady=(22, 18))
        tk.Label(
            brand, text="AstroPhysics Suite", background=self.palette.bg_hero, foreground=self.palette.ink,
            font=(self.fonts.heading, 13, "bold"),
        ).pack(anchor="w")
        tk.Label(
            brand, text="Estación de descubrimiento", background=self.palette.bg_hero, foreground=self.palette.ink_3,
            font=(self.fonts.body, 8),
        ).pack(anchor="w")

        self._nav_buttons: dict[str, tk.Button] = {}
        nav_frame = tk.Frame(self.sidebar, background=self.palette.bg_hero)
        nav_frame.pack(fill="x", padx=10)
        for key, label in NAV_ITEMS:
            btn = tk.Button(
                nav_frame, text=label, anchor="w", relief="flat", bd=0,
                background=self.palette.bg_hero, foreground=self.palette.ink_2,
                activebackground=self.palette.panel_2, activeforeground=self.palette.ink,
                font=(self.fonts.body, 10, "bold"), padx=14, pady=10, cursor="hand2",
                command=lambda k=key: self.show_view(k),
            )
            btn.pack(fill="x", pady=2)
            self._nav_buttons[key] = btn

        self.content = tk.Frame(container, background=self.palette.bg)
        self.content.pack(side="left", fill="both", expand=True)

        self.views = {
            "project": ProjectView(self.content, self),
            "new_observation": NewObservationView(self.content, self),
            "analysis": AnalysisView(self.content, self),
            "candidates": CandidatesView(self.content, self),
            "candidate_detail": CandidateDetailView(self.content, self),
            "settings": SettingsView(self.content, self),
            "diagnostics": DiagnosticsView(self.content, self),
        }
        for view in self.views.values():
            view.place(in_=self.content, relwidth=1, relheight=1)
            view.lower()

    # ---------------------------------------------------------------- navegación
    def show_view(self, key: str, **kwargs) -> None:
        view = self.views[key]
        view.lift()
        if hasattr(view, "on_show"):
            view.on_show(**kwargs)
        for nav_key, btn in self._nav_buttons.items():
            selected = nav_key == key or (nav_key == "candidates" and key == "candidate_detail")
            btn.configure(
                background=self.palette.panel_2 if selected else self.palette.bg_hero,
                foreground=self.palette.accent if selected else self.palette.ink_2,
            )

    def open_candidate(self, candidate_id: str) -> None:
        self.selected_candidate_id = candidate_id
        self.show_view("candidate_detail")

    # ---------------------------------------------------------------- análisis
    def start_analysis(self, *, target_name: str, images: list[tuple[str, str]]) -> None:
        from services.discovery_service import DiscoveryParams

        params = self.views["settings"].current_params() if "settings" in self.views else DiscoveryParams()
        self.active_job = DiscoveryJob(target_name=target_name, images=images, params=params, pipeline_version=PIPELINE_VERSION)
        self.active_job.start()
        self.show_view("analysis")
