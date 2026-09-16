"""Configuración avanzada del Discovery Engine: los parámetros técnicos
que "Nueva observación" deliberadamente no expone (ver
`new_observation_view.py`). `current_params()` es el único contrato que
el resto de la GUI necesita de esta vista (`App.start_analysis`).
"""
from __future__ import annotations

import tkinter as tk

from services.discovery_service import DiscoveryParams

FIELDS = [
    ("fwhm_px", "FWHM esperado (px)", "Tamaño típico de una fuente puntual, en píxeles."),
    ("threshold_sigma", "Umbral de detección (σ)", "Nivel de significancia mínimo sobre el ruido de fondo."),
    ("max_sources", "Máximo de fuentes", "Límite de detecciones procesadas por imagen."),
    ("match_radius_arcsec", "Radio de cruce (arcsec)", "Distancia máxima para asociar una detección a un catálogo."),
    ("gaia_mag_limit", "Límite de magnitud Gaia", "Magnitud más débil consultada en Gaia DR3."),
]


class SettingsView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)
        defaults = DiscoveryParams()

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 6))
        tk.Label(header, text="CONFIGURACIÓN", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(anchor="w")
        tk.Label(header, text="Parámetros avanzados del análisis", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold")).pack(
            anchor="w", pady=(2, 0)
        )
        tk.Label(
            header, text="Se aplican al siguiente análisis que lances desde \"Nueva observación\".",
            background=p.bg, foreground=p.ink_2, font=(app.fonts.body, 10),
        ).pack(anchor="w", pady=(4, 0))

        form = tk.Frame(self, background=p.bg)
        form.pack(fill="x", padx=36, pady=(20, 0))

        self._vars: dict[str, tk.StringVar] = {}
        for key, label, help_text in FIELDS:
            row = tk.Frame(form, background=p.bg)
            row.pack(fill="x", pady=8)
            tk.Label(row, text=label, background=p.bg, foreground=p.ink, font=(app.fonts.body, 10, "bold")).pack(anchor="w")
            tk.Label(row, text=help_text, background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 8)).pack(anchor="w", pady=(0, 4))
            var = tk.StringVar(value=str(getattr(defaults, key)))
            entry = tk.Entry(
                row, textvariable=var, font=(app.fonts.mono, 10), background=p.panel, foreground=p.ink,
                relief="solid", bd=1, highlightbackground=p.border, highlightcolor=p.accent, width=16,
            )
            entry.pack(anchor="w", ipady=5)
            self._vars[key] = var

        footer = tk.Frame(self, background=p.bg)
        footer.pack(fill="x", padx=36, pady=20)
        self.status_label = tk.Label(footer, text="", background=p.bg, foreground=p.coral, font=(app.fonts.body, 9))
        self.status_label.pack(anchor="w")
        tk.Button(
            footer, text="Restaurar valores por defecto", relief="flat", bd=0, cursor="hand2",
            background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 9),
            command=self._restore_defaults,
        ).pack(anchor="w", pady=(6, 0))

    def on_show(self) -> None:
        self.status_label.configure(text="")

    def _restore_defaults(self) -> None:
        defaults = DiscoveryParams()
        for key, var in self._vars.items():
            var.set(str(getattr(defaults, key)))
        self.status_label.configure(text="")

    def current_params(self) -> DiscoveryParams:
        """Lee los campos de texto y construye un `DiscoveryParams`. Un
        valor no numérico o fuera de dominio se ignora silenciosamente en
        favor del valor por defecto correspondiente -- el análisis nunca
        debe bloquearse por un error de tecleo en configuración avanzada,
        y el mensaje de estado deja constancia de qué se ignoró."""
        defaults = DiscoveryParams()
        kwargs: dict[str, float] = {}
        ignored: list[str] = []
        for key, label, _ in FIELDS:
            raw = self._vars[key].get().strip()
            default_value = getattr(defaults, key)
            try:
                value = int(raw) if isinstance(default_value, int) else float(raw)
                if value <= 0:
                    raise ValueError
                kwargs[key] = value
            except (TypeError, ValueError):
                ignored.append(label)
        if ignored:
            self.status_label.configure(text=f"Valor inválido, se usó el valor por defecto: {', '.join(ignored)}")
        else:
            self.status_label.configure(text="")
        return DiscoveryParams(**kwargs)
