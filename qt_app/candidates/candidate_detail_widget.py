"""Detalle de un candidato -- la vista de trabajo real: toda la cadena
de evidencia (identificación, caracterización, física, anomalía,
temporal, movimiento, artefactos, calidad, procedencia), con las únicas
acciones que el encargo permite sobre un `Candidate`: que un humano lo
conserve, lo descarte o lo marque para revisión posterior. Nunca declara
aquí un descubrimiento oficial -- solo registra la decisión humana
(`Candidate.mark_reviewed`). Migrado de `gui/views/candidate_detail_view.py`
(Fase 8, Tkinter) al taller Qt.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QFileDialog,
    QFormLayout,
    QFrame,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from astrophysics_suite.core.enums import ReviewState
from astrophysics_suite.core.quantity import Quantity
from qt_app.candidates.badge import Badge
from qt_app.candidates.mappings import REVIEW_LABEL_ES, STATE_COLOR_ATTR, STATE_LABEL_ES
from services.app_preferences import AppPreferencesStore
from services.session_state import SessionState

logger = logging.getLogger(__name__)

_REVIEWER_NAME_PREFERENCE_KEY = "candidate_review.reviewer_name"
DEFAULT_REVIEWER_NAME = "Revisor"
"""Valor de partida cuando todavía no se ha guardado ningún nombre real
-- el taller no tiene un sistema de usuarios/sesiones de inicio de
sesión, así que la autoría real es lo que el propio revisor teclea la
primera vez (`_review`), persistido como preferencia y reutilizado
como valor por defecto en las siguientes revisiones."""


def _fmt_quantity(q: Quantity | None) -> str:
    if q is None or not q.is_available:
        return "NO DISPONIBLE"
    text = f"{q.value:.4g}"
    if q.error is not None:
        text += f" ± {q.error:.2g}"
    if q.unit:
        text += f" {q.unit}"
    return text


class CandidateDetailWidget(QWidget):
    review_changed = Signal()
    report_generated = Signal(str)
    """Emitida con la ruta real tras generar un informe -- este widget no
    tiene barra de estado propia (vive dentro de una subventana MDI); el
    éxito se comunica así, nunca con un diálogo modal bloqueante como el
    que sí usa `QMessageBox.critical` para un error real."""

    def __init__(self, candidate_id: str, session_state: SessionState, palette, parent=None, preferences: AppPreferencesStore | None = None):
        super().__init__(parent)
        self.candidate_id = candidate_id
        self.session_state = session_state
        self.palette = palette
        self.preferences = preferences or AppPreferencesStore()

        outer = QVBoxLayout(self)
        header = QVBoxLayout()
        title_row = QHBoxLayout()
        self.title_label = QLabel("")
        self.title_label.setObjectName("SectionHeading")
        title_row.addWidget(self.title_label)
        self.badge_container = QHBoxLayout()
        title_row.addLayout(self.badge_container)
        title_row.addStretch(1)
        header.addLayout(title_row)

        self.subtitle_label = QLabel("")
        self.subtitle_label.setObjectName("Muted")
        header.addWidget(self.subtitle_label)

        actions = QHBoxLayout()
        self.keep_button = QPushButton("Conservar")
        self.keep_button.clicked.connect(lambda: self._review(ReviewState.KEPT))
        self.flag_button = QPushButton("Marcar")
        self.flag_button.clicked.connect(lambda: self._review(ReviewState.FLAGGED))
        self.reject_button = QPushButton("Descartar")
        self.reject_button.clicked.connect(lambda: self._review(ReviewState.REJECTED))
        self.report_button = QPushButton("Generar informe científico...")
        self.report_button.clicked.connect(self._generate_report)
        for button in (self.keep_button, self.flag_button, self.reject_button, self.report_button):
            actions.addWidget(button)
        actions.addStretch(1)
        header.addLayout(actions)
        outer.addLayout(header)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        self.sections_container = QWidget()
        self.sections_layout = QVBoxLayout(self.sections_container)
        self.sections_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        scroll.setWidget(self.sections_container)
        outer.addWidget(scroll)

        session_state.on_change(self._refresh)
        self._refresh()

    def _candidate(self):
        for candidate in self.session_state.candidates:
            if candidate.candidate_id == self.candidate_id:
                return candidate
        return None

    def _review(self, new_state: ReviewState) -> None:
        candidate = self._candidate()
        if candidate is None:
            return
        last_reviewer = self.preferences.get(_REVIEWER_NAME_PREFERENCE_KEY, DEFAULT_REVIEWER_NAME)
        reviewer, ok = QInputDialog.getText(self, "Nota de revisión", "Tu nombre (queda registrado como autor de esta revisión):", text=last_reviewer)
        if not ok or not reviewer.strip():
            return
        reviewer = reviewer.strip()
        note, ok = QInputDialog.getMultiLineText(
            self, "Nota de revisión", "Motivo (queda registrado en el historial del candidato):"
        )
        if not ok:
            return
        self.preferences.set(_REVIEWER_NAME_PREFERENCE_KEY, reviewer)
        updated = candidate.mark_reviewed(new_state=new_state, author=reviewer, note=note, reviewed_at=datetime.now(timezone.utc))
        self.session_state.replace_candidate(updated)
        self.review_changed.emit()

    def _generate_report(self) -> None:
        from astrophysics_suite.export.html import export_html
        from astrophysics_suite.reporting.candidate_report import build_candidate_report

        candidate = self._candidate()
        if candidate is None:
            return
        observation = next((o for o in self.session_state.observations if o.observation_id == candidate.observation_id), None)
        path, _ = QFileDialog.getSaveFileName(self, "Generar informe científico", f"{candidate.candidate_id}.html", "HTML (*.html)")
        if not path:
            return
        try:
            report = build_candidate_report(candidate, observation=observation, pipeline_version=candidate.provenance.pipeline_version)
            export_html(report, path)
        except Exception as exc:  # noqa: BLE001 -- error real de generación/escritura, debe ser visible
            logger.error("No se pudo generar el informe de %s en %s: %s", candidate.candidate_id, path, exc)
            QMessageBox.critical(self, "Generar informe científico", f"No se pudo generar el informe en «{Path(path).name}»:\n\n{exc}")
            return
        logger.info("Informe científico de %s generado en %s (%d secciones)", candidate.candidate_id, path, len(report.sections))
        self.report_generated.emit(path)

    def _refresh(self) -> None:
        p = self.palette
        while self.badge_container.count():
            item = self.badge_container.takeAt(0)
            if item.widget():
                item.widget().deleteLater()
        while self.sections_layout.count():
            item = self.sections_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        candidate = self._candidate()
        if candidate is None:
            self.title_label.setText("Candidato no encontrado")
            self.subtitle_label.setText("")
            return

        self.title_label.setText(candidate.candidate_id)
        coords = f"x={candidate.position.x_px:.1f}  y={candidate.position.y_px:.1f}"
        if candidate.position.has_sky_coordinates:
            coords = f"RA={candidate.position.ra_deg:.5f}   Dec={candidate.position.dec_deg:.5f}"
        self.subtitle_label.setText(f"{candidate.observation_id}  ·  {coords}")

        state_key = candidate.identification_state.value
        state_color = getattr(p, STATE_COLOR_ATTR.get(state_key, "ink_faint"))
        self.badge_container.addWidget(Badge(STATE_LABEL_ES.get(state_key, state_key), fg=p.accent_ink, bg=state_color))

        pending = candidate.review_state == ReviewState.PENDING
        self.keep_button.setEnabled(pending)
        self.flag_button.setEnabled(pending)
        self.reject_button.setEnabled(pending)

        self._section_overview(candidate)
        self._section_evidence_chain(candidate)
        self._section_physical(candidate)
        self._section_anomaly(candidate)
        self._section_temporal_motion(candidate)
        self._section_catalog(candidate)
        self._section_quality_artifacts(candidate)
        self._section_review_history(candidate)
        self._section_provenance(candidate)

    def _section(self, title: str) -> QFormLayout:
        p = self.palette
        heading = QLabel(title.upper())
        heading.setStyleSheet(f"color: {p.ink_muted}; font-size: 9px; font-weight: 700; margin-top: 8px;")
        self.sections_layout.addWidget(heading)

        card = QFrame()
        card.setStyleSheet(f"QFrame {{ background: {p.bg_panel}; border: 1px solid {p.border}; border-radius: 4px; }}")
        form = QFormLayout(card)
        self.sections_layout.addWidget(card)
        return form

    def _kv(self, form: QFormLayout, label: str, value: str) -> None:
        p = self.palette
        label_widget = QLabel(label)
        label_widget.setStyleSheet(f"color: {p.ink_muted};")
        value_widget = QLabel(value)
        value_widget.setStyleSheet(f"color: {p.ink}; font-family: Consolas, monospace;")
        value_widget.setWordWrap(True)
        form.addRow(label_widget, value_widget)

    def _muted_note(self, form: QFormLayout, text: str) -> None:
        p = self.palette
        note = QLabel(text)
        note.setStyleSheet(f"color: {p.ink_faint};")
        form.addRow(note)

    def _section_overview(self, candidate) -> None:
        form = self._section("Identificación y caracterización")
        self._kv(form, "Morfología", candidate.morphology.morphology_class.value)
        self._kv(form, "Tamaño", _fmt_quantity(candidate.size))
        self._kv(form, "S/N", _fmt_quantity(candidate.snr))
        self._kv(form, "Bandas", ", ".join(candidate.bands) or "—")
        for band, flux in candidate.flux.items():
            self._kv(form, f"Flujo ({band})", _fmt_quantity(flux))

    def _section_evidence_chain(self, candidate) -> None:
        anomaly = candidate.anomaly_evidence
        n_independent = anomaly.independent_evidence_count if anomaly else 0
        form = self._section("Cadena de evidencia")
        self._kv(form, "Evidencias independientes", str(n_independent))
        self._kv(form, "Coincidencias de catálogo", str(len(candidate.catalog_matches)))
        self._kv(form, "Consultas sin coincidencia", str(len(candidate.catalog_non_matches)))
        self._kv(form, "Evaluaciones de IA", str(len(candidate.ai_evidence)))

    def _section_physical(self, candidate) -> None:
        inference = candidate.physical_evidence
        form = self._section("Inferencia física")
        if inference is None:
            self._muted_note(form, "Sin inferencia física para este candidato.")
            return
        self._kv(form, "Familia de objeto", inference.object_family or "—")
        self._kv(form, "Modelo", inference.model_id or "(sin modelo aplicado)")
        self._kv(form, "Hipótesis", ", ".join(inference.model_hypotheses) or "—")
        self._kv(form, "Dominio válido", "Sí" if inference.domain_valid else "No")
        for name, q in inference.parameters.items():
            self._kv(form, name, _fmt_quantity(q))

    def _section_anomaly(self, candidate) -> None:
        anomaly = candidate.anomaly_evidence
        form = self._section("Vector de anomalía")
        if anomaly is None:
            self._muted_note(form, "Sin evaluación de anomalía para este candidato.")
            return
        for name in ("photometric", "morphological", "spectral", "temporal", "astrometric", "spatial", "physical"):
            self._kv(form, name.capitalize(), _fmt_quantity(getattr(anomaly, name)))

    def _section_temporal_motion(self, candidate) -> None:
        temporal = candidate.temporal_evidence
        motion = candidate.motion_evidence
        if temporal is None and motion is None:
            return
        form = self._section("Evidencia temporal y de movimiento")
        if temporal is not None:
            self._kv(form, "Épocas (temporal)", str(temporal.n_epochs))
            self._kv(form, "Aparición detectada", "Sí" if temporal.appearance_detected else "No")
            self._kv(form, "Desaparición detectada", "Sí" if temporal.disappearance_detected else "No")
            self._kv(form, "Cambio de brillo", _fmt_quantity(temporal.brightness_change))
            self._kv(form, "Candidato variable", "Sí" if temporal.variable_candidate else "No")
        if motion is not None:
            self._kv(form, "Épocas (movimiento)", str(motion.n_epochs_used))
            self._kv(form, "Movimiento propio total", _fmt_quantity(motion.pm_total))
            self._kv(form, "Candidato en movimiento", "Sí" if motion.moving_source_candidate else "No")

    def _section_catalog(self, candidate) -> None:
        form = self._section("Catálogos")
        if not candidate.catalog_matches and not candidate.catalog_non_matches:
            self._muted_note(form, "Sin consultas de catálogo registradas.")
            return
        for match in candidate.catalog_matches:
            label = f"{match.catalog}  ·  {match.catalog_id}"
            value = f"{match.separation_arcsec:.2f}″  {match.object_type or ''}".strip()
            self._kv(form, label, value)
        for query in candidate.catalog_non_matches:
            self._kv(form, f"{query.catalog} (sin match)", query.reason or f"radio {query.radius_arcsec}″")

    def _section_quality_artifacts(self, candidate) -> None:
        form = self._section("Calidad y artefactos")
        self._kv(form, "Nivel general", candidate.quality.overall_level.value)
        for check in candidate.quality.checks:
            self._kv(form, check.name, f"{check.level.value}  {check.detail}".strip())
        for artifact in candidate.artifact_checks:
            if artifact.flagged:
                self._kv(form, f"Artefacto: {artifact.kind.value}", artifact.notes or "marcado")

    def _section_review_history(self, candidate) -> None:
        if not candidate.review_notes:
            return
        form = self._section("Historial de revisión")
        for note in candidate.review_notes:
            label = f"{note.created_at:%Y-%m-%d %H:%M}  ·  {note.author}"
            value = f"{REVIEW_LABEL_ES.get(note.new_state.value, note.new_state.value)}  —  {note.note}"
            self._kv(form, label, value)

    def _section_provenance(self, candidate) -> None:
        provenance = candidate.provenance
        form = self._section("Procedencia")
        self._kv(form, "Pipeline", provenance.pipeline_version)
        self._kv(form, "Motor", f"{provenance.engine} {provenance.engine_version}")
        self._kv(form, "Producido", f"{provenance.produced_at:%Y-%m-%d %H:%M UTC}")
        if provenance.warnings:
            self._kv(form, "Advertencias", "; ".join(provenance.warnings))
