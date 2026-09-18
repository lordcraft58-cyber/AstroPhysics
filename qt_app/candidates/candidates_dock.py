"""Lista de candidatos -- el centro real del producto (ver el encargo
original: "el centro del producto no debe ser la imagen; debe ser el
candidato científico y su evidencia"), ahora como panel acoplable del
taller Qt. Filtrable por estado de identificación y de revisión; un
doble clic abre el detalle completo en el área MDI.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QComboBox, QFrame, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget

from qt_app.candidates.badge import Badge
from qt_app.candidates.mappings import REVIEW_COLOR_ATTR, REVIEW_LABEL_ES, STATE_COLOR_ATTR, STATE_LABEL_ES
from services.session_state import SessionState

IDENTIFICATION_FILTER_ALL = "Todos los estados"
REVIEW_FILTER_ALL = "Cualquier revisión"


class CandidatesDock(QWidget):
    candidate_activated = Signal(str)

    def __init__(self, session_state: SessionState, palette, parent=None):
        super().__init__(parent)
        self.session_state = session_state
        self.palette = palette

        layout = QVBoxLayout(self)
        layout.setContentsMargins(6, 6, 6, 6)

        self.title_label = QLabel("0 candidato(s)")
        self.title_label.setObjectName("SectionHeading")
        layout.addWidget(self.title_label)

        filters = QHBoxLayout()
        self.identification_filter = QComboBox()
        self.identification_filter.addItem(IDENTIFICATION_FILTER_ALL)
        self.identification_filter.addItems(list(STATE_LABEL_ES.values()))
        self.identification_filter.currentIndexChanged.connect(self._render)
        filters.addWidget(self.identification_filter)

        self.review_filter = QComboBox()
        self.review_filter.addItem(REVIEW_FILTER_ALL)
        self.review_filter.addItems(list(REVIEW_LABEL_ES.values()))
        self.review_filter.currentIndexChanged.connect(self._render)
        filters.addWidget(self.review_filter)
        layout.addLayout(filters)

        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.list_container = QWidget()
        self.list_layout = QVBoxLayout(self.list_container)
        self.list_layout.setAlignment(Qt.AlignmentFlag.AlignTop)
        self.scroll.setWidget(self.list_container)
        layout.addWidget(self.scroll)

        session_state.on_change(self.refresh)
        self.refresh()

    def refresh(self) -> None:
        self.title_label.setText(f"{len(self.session_state.candidates)} candidato(s)")
        self._render()

    def _filtered_candidates(self):
        candidates = self.session_state.candidates
        id_filter = self.identification_filter.currentText()
        if id_filter != IDENTIFICATION_FILTER_ALL:
            candidates = [c for c in candidates if STATE_LABEL_ES.get(c.identification_state.value) == id_filter]
        review_filter = self.review_filter.currentText()
        if review_filter != REVIEW_FILTER_ALL:
            candidates = [c for c in candidates if REVIEW_LABEL_ES.get(c.review_state.value) == review_filter]
        return sorted(candidates, key=lambda c: -(c.snr.value if c.snr else 0))

    def _render(self) -> None:
        while self.list_layout.count():
            item = self.list_layout.takeAt(0)
            if item.widget():
                item.widget().deleteLater()

        candidates = self._filtered_candidates()
        if not candidates:
            empty = QLabel("Ningún candidato coincide con los filtros actuales.")
            empty.setObjectName("Muted")
            self.list_layout.addWidget(empty)
            return

        for candidate in candidates:
            self.list_layout.addWidget(self._build_row(candidate))

    def _build_row(self, candidate) -> QFrame:
        p = self.palette
        row = QFrame()
        row.setObjectName("CandidateRow")
        row.setStyleSheet(
            f"""
            QFrame#CandidateRow {{ background: {p.bg_panel}; border: 1px solid {p.border}; border-radius: 4px; }}
            QFrame#CandidateRow:hover {{ border-color: {p.accent}; }}
            """
        )
        row.setCursor(Qt.CursorShape.PointingHandCursor)
        row.mousePressEvent = lambda event, cid=candidate.candidate_id: self.candidate_activated.emit(cid)  # noqa: E731

        outer = QVBoxLayout(row)
        id_label = QLabel(candidate.candidate_id)
        id_label.setStyleSheet(f"color: {p.ink}; font-weight: 700; font-family: Consolas, monospace; font-size: 10px;")
        id_label.setWordWrap(True)
        outer.addWidget(id_label)

        badges = QHBoxLayout()
        state_key = candidate.identification_state.value
        state_color = getattr(p, STATE_COLOR_ATTR.get(state_key, "ink_faint"))
        badges.addWidget(Badge(STATE_LABEL_ES.get(state_key, state_key), fg=p.accent_ink, bg=state_color))

        review_key = candidate.review_state.value
        if review_key != "PENDING":
            review_color = getattr(p, REVIEW_COLOR_ATTR.get(review_key, "ink_faint"))
            badges.addWidget(Badge(REVIEW_LABEL_ES.get(review_key, review_key), fg=p.accent_ink, bg=review_color))
        badges.addStretch(1)
        outer.addLayout(badges)

        fields = QHBoxLayout()
        snr_text = f"{candidate.snr.value:.1f}" if candidate.snr else "—"
        fields.addWidget(self._field("S/N", snr_text, p))
        fields.addWidget(self._field("Bandas", ", ".join(candidate.bands) or "—", p))
        fields.addWidget(self._field("Calidad", candidate.quality.overall_level.value, p))
        n_matches = len(candidate.catalog_matches)
        fields.addWidget(self._field("Catálogo", f"{n_matches} coincidencia(s)" if n_matches else "sin coincidencia", p))
        fields.addStretch(1)
        outer.addLayout(fields)
        return row

    def _field(self, label: str, value: str, p) -> QWidget:
        cell = QWidget()
        cell_layout = QVBoxLayout(cell)
        cell_layout.setContentsMargins(0, 4, 16, 0)
        cell_layout.setSpacing(1)
        label_widget = QLabel(label.upper())
        label_widget.setStyleSheet(f"color: {p.ink_faint}; font-size: 8px; font-weight: 700;")
        value_widget = QLabel(value)
        value_widget.setStyleSheet(f"color: {p.ink}; font-family: Consolas, monospace; font-size: 10px;")
        cell_layout.addWidget(label_widget)
        cell_layout.addWidget(value_widget)
        return cell
