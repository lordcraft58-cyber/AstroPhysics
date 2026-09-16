"""Lista de candidatos -- la pantalla central del producto (ver el
encargo: "el centro del producto no debe ser la imagen; debe ser el
candidato científico y su evidencia"). Tarjetas con badge de color
semántico, filtrables por estado de identificación y de revisión.
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk

from gui.theme import QUALITY_COLOR_KEY, REVIEW_COLOR_KEY, REVIEW_LABEL_ES, STATE_COLOR_KEY, STATE_LABEL_ES, color_for
from gui.widgets.badge import Badge
from gui.widgets.card import Card
from gui.widgets.scrollable import ScrollableFrame

IDENTIFICATION_FILTER_ALL = "Todos los estados"
REVIEW_FILTER_ALL = "Cualquier revisión"


class CandidatesView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 6))
        tk.Label(header, text="CANDIDATOS", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(anchor="w")
        self.title_label = tk.Label(header, text="", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold"))
        self.title_label.pack(anchor="w", pady=(2, 0))

        filters = tk.Frame(self, background=p.bg)
        filters.pack(fill="x", padx=36, pady=(14, 10))

        self.identification_filter = tk.StringVar(value=IDENTIFICATION_FILTER_ALL)
        identification_values = [IDENTIFICATION_FILTER_ALL] + list(STATE_LABEL_ES.values())
        ttk.Combobox(
            filters, textvariable=self.identification_filter, values=identification_values, state="readonly", width=22
        ).pack(side="left", padx=(0, 10))

        self.review_filter = tk.StringVar(value=REVIEW_FILTER_ALL)
        review_values = [REVIEW_FILTER_ALL] + list(REVIEW_LABEL_ES.values())
        ttk.Combobox(filters, textvariable=self.review_filter, values=review_values, state="readonly", width=18).pack(
            side="left", padx=(0, 10)
        )

        for var in (self.identification_filter, self.review_filter):
            var.trace_add("write", lambda *_: self._render())

        self.scroll = ScrollableFrame(self, background=p.bg)
        self.scroll.pack(fill="both", expand=True, padx=36, pady=(0, 24))

    def on_show(self) -> None:
        self.title_label.configure(text=f"{len(self.app.state.candidates)} candidato(s)")
        self._render()

    def _render(self) -> None:
        p = self.app.palette
        for widget in self.scroll.body.winfo_children():
            widget.destroy()

        candidates = self._filtered_candidates()
        if not candidates:
            empty = Card(self.scroll.body, p, padding=24)
            empty.pack(fill="x", pady=(0, 10))
            tk.Label(
                empty.inner, text="Ningún candidato coincide con los filtros actuales.",
                background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 10),
            ).pack(anchor="w")
            return

        for candidate in sorted(candidates, key=lambda c: -(c.snr.value if c.snr else 0)):
            self._render_row(candidate)

    def _filtered_candidates(self):
        candidates = self.app.state.candidates
        id_filter = self.identification_filter.get()
        if id_filter != IDENTIFICATION_FILTER_ALL:
            candidates = [c for c in candidates if STATE_LABEL_ES.get(c.identification_state.value) == id_filter]
        review_filter = self.review_filter.get()
        if review_filter != REVIEW_FILTER_ALL:
            candidates = [c for c in candidates if REVIEW_LABEL_ES.get(c.review_state.value) == review_filter]
        return candidates

    def _render_row(self, candidate) -> None:
        p = self.app.palette
        row = Card(self.scroll.body, p, padding=14)
        row.pack(fill="x", pady=(0, 8))
        row.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))
        row.inner.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))

        top = tk.Frame(row.inner, background=p.panel)
        top.pack(fill="x")
        top.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))

        left = tk.Frame(top, background=p.panel)
        left.pack(side="left", fill="x", expand=True)
        left.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))
        id_label = tk.Label(left, text=candidate.candidate_id, background=p.panel, foreground=p.ink, font=(self.app.fonts.mono, 10, "bold"))
        id_label.pack(anchor="w")
        id_label.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))
        coords = f"x={candidate.position.x_px:.1f} y={candidate.position.y_px:.1f}"
        if candidate.position.has_sky_coordinates:
            coords = f"RA={candidate.position.ra_deg:.5f}  Dec={candidate.position.dec_deg:.5f}"
        coords_label = tk.Label(left, text=coords, background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 8))
        coords_label.pack(anchor="w")
        coords_label.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))

        right = tk.Frame(top, background=p.panel)
        right.pack(side="right")
        state_key = candidate.identification_state.value
        Badge(
            right, text=STATE_LABEL_ES.get(state_key, state_key),
            fg=color_for(p, STATE_COLOR_KEY.get(state_key, "ink_3")),
            bg=_soft(p, STATE_COLOR_KEY.get(state_key, "ink_3")),
            fonts=self.app.fonts, panel_bg=p.panel,
        ).pack(side="left", padx=(0, 6))
        review_key = candidate.review_state.value
        if review_key != "PENDING":
            Badge(
                right, text=REVIEW_LABEL_ES.get(review_key, review_key),
                fg=color_for(p, REVIEW_COLOR_KEY.get(review_key, "ink_3")), bg=p.panel_2,
                fonts=self.app.fonts, panel_bg=p.panel,
            ).pack(side="left")

        fields = tk.Frame(row.inner, background=p.panel)
        fields.pack(fill="x", pady=(10, 0))
        fields.bind("<Button-1>", lambda e: self.app.open_candidate(candidate.candidate_id))
        self._field(fields, "S/N", f"{candidate.snr.value:.1f}" if candidate.snr else "—")
        self._field(fields, "Bandas", ", ".join(candidate.bands) or "—")
        self._field(fields, "Calidad", candidate.quality.overall_level.value)
        n_matches = len(candidate.catalog_matches)
        self._field(fields, "Catálogo", f"{n_matches} coincidencia(s)" if n_matches else "sin coincidencia")

    def _field(self, parent: tk.Frame, label: str, value: str) -> None:
        p = self.app.palette
        cell = tk.Frame(parent, background=p.panel)
        cell.pack(side="left", padx=(0, 22))
        tk.Label(cell, text=label.upper(), background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 7, "bold")).pack(anchor="w")
        tk.Label(cell, text=value, background=p.panel, foreground=p.ink, font=(self.app.fonts.mono, 9)).pack(anchor="w")


def _soft(palette, key: str) -> str:
    return getattr(palette, f"{key}_soft", palette.panel_2)
