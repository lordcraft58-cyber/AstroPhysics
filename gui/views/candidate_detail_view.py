"""Detalle de un candidato -- la vista de trabajo real: toda la cadena de
evidencia (identificación, caracterización, física, anomalía, temporal,
movimiento, artefactos, calidad, procedencia) en un solo lugar, con las
únicas acciones que el encargo permite sobre un Candidate: que un humano
lo conserve, lo descarte o lo marque para revisión posterior. La
aplicación nunca declara aquí un descubrimiento oficial -- solo registra
la decisión humana (`Candidate.mark_reviewed`).
"""
from __future__ import annotations

import tkinter as tk
from datetime import datetime, timezone
from tkinter import simpledialog

from astrophysics_suite.core.enums import ReviewState
from astrophysics_suite.core.quantity import Quantity
from gui.theme import REVIEW_LABEL_ES, STATE_COLOR_KEY, STATE_LABEL_ES, color_for
from gui.widgets.badge import Badge
from gui.widgets.card import Card
from gui.widgets.scrollable import ScrollableFrame

REVIEWER_NAME = "Revisor"
"""Placeholder de autoría -- la sesión no tiene todavía un sistema de
usuarios; queda para una fase posterior (ver docs/audit/10-FASE8-GUI.md)."""


def _fmt_quantity(q: Quantity | None) -> str:
    if q is None or not q.is_available:
        return "NO DISPONIBLE"
    text = f"{q.value:.4g}"
    if q.error is not None:
        text += f" ± {q.error:.2g}"
    if q.unit:
        text += f" {q.unit}"
    return text


class CandidateDetailView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 6))
        back = tk.Button(
            header, text="← Candidatos", relief="flat", bd=0, cursor="hand2",
            background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 9, "bold"),
            command=lambda: app.show_view("candidates"),
        )
        back.pack(anchor="w")

        title_row = tk.Frame(header, background=p.bg)
        title_row.pack(fill="x", pady=(6, 0))
        self.title_label = tk.Label(title_row, text="", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold"))
        self.title_label.pack(side="left")
        self.badges_frame = tk.Frame(title_row, background=p.bg)
        self.badges_frame.pack(side="left", padx=(14, 0))
        self.subtitle_label = tk.Label(header, text="", background=p.bg, foreground=p.ink_3, font=(app.fonts.mono, 9))
        self.subtitle_label.pack(anchor="w", pady=(4, 0))

        actions = tk.Frame(header, background=p.bg)
        actions.pack(anchor="w", pady=(14, 0))
        self.keep_button = tk.Button(
            actions, text="Conservar", relief="flat", bd=0, cursor="hand2",
            background=p.cyan, foreground=p.accent_ink, font=(app.fonts.body, 9, "bold"), padx=16, pady=8,
            command=lambda: self._review(ReviewState.KEPT),
        )
        self.keep_button.pack(side="left")
        self.flag_button = tk.Button(
            actions, text="Marcar", relief="flat", bd=0, cursor="hand2",
            background=p.panel_2, foreground=p.accent, font=(app.fonts.body, 9, "bold"), padx=16, pady=8,
            command=lambda: self._review(ReviewState.FLAGGED),
        )
        self.flag_button.pack(side="left", padx=(8, 0))
        self.reject_button = tk.Button(
            actions, text="Descartar", relief="flat", bd=0, cursor="hand2",
            background=p.panel_2, foreground=p.coral, font=(app.fonts.body, 9, "bold"), padx=16, pady=8,
            command=lambda: self._review(ReviewState.REJECTED),
        )
        self.reject_button.pack(side="left", padx=(8, 0))

        self.scroll = ScrollableFrame(self, background=p.bg)
        self.scroll.pack(fill="both", expand=True, padx=36, pady=(16, 24))

    # ---------------------------------------------------------------- ciclo
    def on_show(self) -> None:
        self._render()

    def _candidate(self):
        candidate_id = self.app.selected_candidate_id
        for candidate in self.app.state.candidates:
            if candidate.candidate_id == candidate_id:
                return candidate
        return None

    def _review(self, new_state: ReviewState) -> None:
        candidate = self._candidate()
        if candidate is None:
            return
        note = simpledialog.askstring(
            "Nota de revisión",
            "Motivo (queda registrado en el historial del candidato):",
            parent=self,
        )
        if note is None:
            return
        updated = candidate.mark_reviewed(
            new_state=new_state, author=REVIEWER_NAME, note=note, reviewed_at=datetime.now(timezone.utc)
        )
        self.app.state.replace_candidate(updated)
        self._render()

    # ---------------------------------------------------------------- render
    def _render(self) -> None:
        p = self.app.palette
        for widget in self.scroll.body.winfo_children():
            widget.destroy()
        for widget in self.badges_frame.winfo_children():
            widget.destroy()

        candidate = self._candidate()
        if candidate is None:
            self.title_label.configure(text="Candidato no encontrado")
            self.subtitle_label.configure(text="")
            return

        self.title_label.configure(text=candidate.candidate_id)
        coords = f"x={candidate.position.x_px:.1f}  y={candidate.position.y_px:.1f}"
        if candidate.position.has_sky_coordinates:
            coords = f"RA={candidate.position.ra_deg:.5f}   Dec={candidate.position.dec_deg:.5f}"
        self.subtitle_label.configure(text=f"{candidate.observation_id}  ·  {coords}")

        state_key = candidate.identification_state.value
        Badge(
            self.badges_frame, text=STATE_LABEL_ES.get(state_key, state_key),
            fg=color_for(p, STATE_COLOR_KEY.get(state_key, "ink_3")), bg=p.panel_2,
            fonts=self.app.fonts, panel_bg=p.bg,
        ).pack(side="left")

        pending = candidate.review_state == ReviewState.PENDING
        self.keep_button.configure(state="normal" if pending else "disabled")
        self.flag_button.configure(state="normal" if pending else "disabled")
        self.reject_button.configure(state="normal" if pending else "disabled")

        self._section_overview(candidate)
        self._section_evidence_chain(candidate)
        self._section_physical(candidate)
        self._section_anomaly(candidate)
        self._section_temporal_motion(candidate)
        self._section_catalog(candidate)
        self._section_quality_artifacts(candidate)
        self._section_review_history(candidate)
        self._section_provenance(candidate)

    def _section(self, title: str) -> Card:
        p = self.app.palette
        tk.Label(
            self.scroll.body, text=title.upper(), background=p.bg, foreground=p.ink_3, font=(self.app.fonts.mono, 8, "bold")
        ).pack(anchor="w", pady=(14, 4))
        card = Card(self.scroll.body, p, padding=18)
        card.pack(fill="x")
        return card

    def _kv_row(self, parent: tk.Frame, label: str, value: str) -> None:
        p = self.app.palette
        row = tk.Frame(parent, background=p.panel)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 9), width=22, anchor="w").pack(
            side="left"
        )
        tk.Label(row, text=value, background=p.panel, foreground=p.ink, font=(self.app.fonts.mono, 9), anchor="w").pack(
            side="left", fill="x", expand=True
        )

    def _section_overview(self, candidate) -> None:
        card = self._section("Identificación y caracterización")
        self._kv_row(card.inner, "Morfología", candidate.morphology.morphology_class.value)
        self._kv_row(card.inner, "Tamaño", _fmt_quantity(candidate.size))
        self._kv_row(card.inner, "S/N", _fmt_quantity(candidate.snr))
        self._kv_row(card.inner, "Bandas", ", ".join(candidate.bands) or "—")
        for band, flux in candidate.flux.items():
            self._kv_row(card.inner, f"Flujo ({band})", _fmt_quantity(flux))

    def _section_evidence_chain(self, candidate) -> None:
        anomaly = candidate.anomaly_evidence
        n_independent = anomaly.independent_evidence_count if anomaly else 0
        card = self._section("Cadena de evidencia")
        self._kv_row(card.inner, "Evidencias independientes", str(n_independent))
        self._kv_row(card.inner, "Coincidencias de catálogo", str(len(candidate.catalog_matches)))
        self._kv_row(card.inner, "Consultas sin coincidencia", str(len(candidate.catalog_non_matches)))
        self._kv_row(card.inner, "Evaluaciones de IA", str(len(candidate.ai_evidence)))

    def _section_physical(self, candidate) -> None:
        inference = candidate.physical_evidence
        card = self._section("Inferencia física")
        if inference is None:
            tk.Label(
                card.inner, text="Sin inferencia física para este candidato.",
                background=self.app.palette.panel, foreground=self.app.palette.ink_3, font=(self.app.fonts.body, 9),
            ).pack(anchor="w")
            return
        self._kv_row(card.inner, "Familia de objeto", inference.object_family or "—")
        self._kv_row(card.inner, "Modelo", inference.model_id or "(sin modelo aplicado)")
        self._kv_row(card.inner, "Hipótesis", ", ".join(inference.model_hypotheses) or "—")
        self._kv_row(card.inner, "Dominio válido", "Sí" if inference.domain_valid else "No")
        for name, q in inference.parameters.items():
            self._kv_row(card.inner, name, _fmt_quantity(q))

    def _section_anomaly(self, candidate) -> None:
        anomaly = candidate.anomaly_evidence
        card = self._section("Vector de anomalía")
        if anomaly is None:
            tk.Label(
                card.inner, text="Sin evaluación de anomalía para este candidato.",
                background=self.app.palette.panel, foreground=self.app.palette.ink_3, font=(self.app.fonts.body, 9),
            ).pack(anchor="w")
            return
        for name in ("photometric", "morphological", "spectral", "temporal", "astrometric", "spatial", "physical"):
            self._kv_row(card.inner, name.capitalize(), _fmt_quantity(getattr(anomaly, name)))

    def _section_temporal_motion(self, candidate) -> None:
        temporal = candidate.temporal_evidence
        motion = candidate.motion_evidence
        if temporal is None and motion is None:
            return
        card = self._section("Evidencia temporal y de movimiento")
        if temporal is not None:
            self._kv_row(card.inner, "Épocas (temporal)", str(temporal.n_epochs))
            self._kv_row(card.inner, "Aparición detectada", "Sí" if temporal.appearance_detected else "No")
            self._kv_row(card.inner, "Desaparición detectada", "Sí" if temporal.disappearance_detected else "No")
            self._kv_row(card.inner, "Cambio de brillo", _fmt_quantity(temporal.brightness_change))
            self._kv_row(card.inner, "Candidato variable", "Sí" if temporal.variable_candidate else "No")
        if motion is not None:
            self._kv_row(card.inner, "Épocas (movimiento)", str(motion.n_epochs_used))
            self._kv_row(card.inner, "Movimiento propio total", _fmt_quantity(motion.pm_total))
            self._kv_row(card.inner, "Candidato en movimiento", "Sí" if motion.moving_source_candidate else "No")

    def _section_catalog(self, candidate) -> None:
        card = self._section("Catálogos")
        if not candidate.catalog_matches and not candidate.catalog_non_matches:
            tk.Label(
                card.inner, text="Sin consultas de catálogo registradas.",
                background=self.app.palette.panel, foreground=self.app.palette.ink_3, font=(self.app.fonts.body, 9),
            ).pack(anchor="w")
            return
        for match in candidate.catalog_matches:
            label = f"{match.catalog}  ·  {match.catalog_id}"
            value = f"{match.separation_arcsec:.2f}″  {match.object_type or ''}".strip()
            self._kv_row(card.inner, label, value)
        for query in candidate.catalog_non_matches:
            self._kv_row(card.inner, f"{query.catalog} (sin match)", query.reason or f"radio {query.radius_arcsec}″")

    def _section_quality_artifacts(self, candidate) -> None:
        card = self._section("Calidad y artefactos")
        self._kv_row(card.inner, "Nivel general", candidate.quality.overall_level.value)
        for check in candidate.quality.checks:
            self._kv_row(card.inner, check.name, f"{check.level.value}  {check.detail}".strip())
        for artifact in candidate.artifact_checks:
            if artifact.flagged:
                self._kv_row(card.inner, f"Artefacto: {artifact.kind.value}", artifact.notes or "marcado")

    def _section_review_history(self, candidate) -> None:
        if not candidate.review_notes:
            return
        card = self._section("Historial de revisión")
        for note in candidate.review_notes:
            label = f"{note.created_at:%Y-%m-%d %H:%M}  ·  {note.author}"
            value = f"{REVIEW_LABEL_ES.get(note.new_state.value, note.new_state.value)}  —  {note.note}"
            self._kv_row(card.inner, label, value)

    def _section_provenance(self, candidate) -> None:
        provenance = candidate.provenance
        card = self._section("Procedencia")
        self._kv_row(card.inner, "Pipeline", provenance.pipeline_version)
        self._kv_row(card.inner, "Motor", f"{provenance.engine} {provenance.engine_version}")
        self._kv_row(card.inner, "Producido", f"{provenance.produced_at:%Y-%m-%d %H:%M UTC}")
        if provenance.warnings:
            self._kv_row(card.inner, "Advertencias", "; ".join(provenance.warnings))
