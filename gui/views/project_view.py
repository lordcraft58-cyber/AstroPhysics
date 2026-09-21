"""Pantalla de inicio: resumen del proyecto en memoria + acceso rápido a
crear una observación nueva. Es lo primero que ve el usuario -- el
encargo pide que el centro del producto sea el candidato científico y su
evidencia, no la imagen; esta pantalla lo refleja mostrando candidatos
pendientes de revisión antes que ninguna otra cosa.
"""
from __future__ import annotations

import tkinter as tk

from gui.widgets.card import Card


class ProjectView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 6))
        tk.Label(header, text="PROYECTO", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(anchor="w")
        self.title_label = tk.Label(header, text="", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 22, "bold"))
        self.title_label.pack(anchor="w", pady=(2, 0))
        tk.Label(
            header, text="El centro de trabajo es el candidato científico y su evidencia, no la imagen.",
            background=p.bg, foreground=p.ink_2, font=(app.fonts.body, 10),
        ).pack(anchor="w", pady=(4, 0))

        cta = tk.Button(
            header, text="+  Nueva observación", relief="flat", bd=0, cursor="hand2",
            background=p.accent, foreground=p.accent_ink, font=(app.fonts.body, 10, "bold"), padx=18, pady=10,
            command=lambda: app.show_view("new_observation"),
        )
        cta.pack(anchor="w", pady=(14, 0))

        self.stats_row = tk.Frame(self, background=p.bg)
        self.stats_row.pack(fill="x", padx=36, pady=(24, 10))

        body = tk.Frame(self, background=p.bg)
        body.pack(fill="both", expand=True, padx=36, pady=(10, 24))
        tk.Label(body, text="Observaciones recientes", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 12, "bold")).pack(
            anchor="w", pady=(0, 10)
        )
        self.list_container = tk.Frame(body, background=p.bg)
        self.list_container.pack(fill="both", expand=True)

    def _stat_card(self, parent, label: str, value: str, color: str) -> None:
        p = self.app.palette
        card = Card(parent, p, padding=16)
        card.pack(side="left", padx=(0, 12), fill="y")
        tk.Label(card.inner, text=value, background=p.panel, foreground=color, font=(self.app.fonts.heading, 22, "bold")).pack(
            anchor="w"
        )
        tk.Label(
            card.inner, text=label.upper(), background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 8, "bold")
        ).pack(anchor="w", pady=(2, 0))

    def on_show(self) -> None:
        p = self.app.palette
        state = self.app.state
        self.title_label.configure(text=state.project_name)

        for widget in self.stats_row.winfo_children():
            widget.destroy()
        self._stat_card(self.stats_row, "Observaciones", str(len(state.observations)), p.ink)
        self._stat_card(self.stats_row, "Candidatos", str(len(state.candidates)), p.cyan)
        self._stat_card(self.stats_row, "Pendientes de revisión", str(len(state.candidates_pending_review())), p.accent)

        for widget in self.list_container.winfo_children():
            widget.destroy()

        if not state.observations:
            empty = Card(self.list_container, p, padding=28)
            empty.pack(fill="x")
            tk.Label(
                empty.inner, text="Todavía no hay observaciones en este proyecto.",
                background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 10),
            ).pack(anchor="w")
            tk.Label(
                empty.inner, text='Usa "Nueva observación" para cargar tus primeras imágenes.',
                background=p.panel, foreground=p.ink_3, font=(self.app.fonts.body, 9),
            ).pack(anchor="w", pady=(4, 0))
            return

        for observation in reversed(state.observations):
            row = Card(self.list_container, p, padding=14)
            row.pack(fill="x", pady=(0, 8))
            top = tk.Frame(row.inner, background=p.panel)
            top.pack(fill="x")
            tk.Label(top, text=observation.target_name or "(sin nombre)", background=p.panel, foreground=p.ink, font=(self.app.fonts.body, 11, "bold")).pack(
                side="left"
            )
            tk.Label(
                top, text=f"{len(observation.images)} imagen(es) · {observation.created_at:%Y-%m-%d %H:%M}",
                background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 8),
            ).pack(side="right")
            bands = ", ".join(sorted({im.band for im in observation.images}))
            tk.Label(row.inner, text=f"Bandas: {bands}", background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 9)).pack(
                anchor="w", pady=(4, 0)
            )
