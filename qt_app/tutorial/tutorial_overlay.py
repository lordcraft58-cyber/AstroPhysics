"""Tutorial guiado de primer arranque (Fase 22, objetivo 5 del encargo):
recorrido interactivo real sobre la interfaz -- resalta controles REALES
de la ventana principal (nunca controles inventados) con una capa
semitransparente y un panel contextual, no un PDF ni un README aparte.

`TutorialStep.target` recibe el `MainWindow` real y devuelve el
rectángulo (en sus coordenadas) del control a resaltar, o `None` para un
paso sin control concreto (bienvenida/cierre) -- así, si algún día un
control cambia de sitio o desaparece, el paso simplemente deja de
resaltar nada en vez de señalar un lugar equivocado.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PySide6.QtCore import QRect, Qt
from PySide6.QtGui import QColor, QPainter, QRegion
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

_HIGHLIGHT_COLOR = QColor("#f0b429")
_DIM_COLOR = QColor(0, 0, 0, 150)
_MARGIN = 4
_PANEL_GAP = 16


@dataclass(frozen=True)
class TutorialStep:
    title: str
    what_it_does: str
    """QUÉ HACE -- vacío para un paso puramente introductorio/de cierre."""
    when_to_use: str
    """CUÁNDO USARLO."""
    what_it_needs: str
    """QUÉ NECESITA."""
    what_it_produces: str
    """QUÉ PRODUCE."""
    target: Callable[[object], "QRect | None"]


class TutorialOverlay(QWidget):
    """Una capa por ventana principal -- se reconstruye cada vez que se
    abre el tutorial (`MainWindow._open_tutorial`), nunca se reutiliza
    entre aperturas."""

    def __init__(self, main_window, steps: list[TutorialStep], *, on_finished: Callable[[], None] | None = None, parent=None):
        super().__init__(parent or main_window)
        if not steps:
            raise ValueError("TutorialOverlay necesita al menos un paso")
        self._main_window = main_window
        self._steps = steps
        self._index = 0
        self._on_finished = on_finished
        self._current_rect: QRect | None = None
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self._panel = QFrame(self)
        self._panel.setObjectName("TutorialPanel")
        self._panel.setFrameShape(QFrame.Shape.StyledPanel)
        self._panel.setStyleSheet(
            "#TutorialPanel { background: #1c2129; border: 1px solid #f0b429; border-radius: 6px; }"
            " QLabel { color: #e8e8e8; }"
        )
        panel_layout = QVBoxLayout(self._panel)
        panel_layout.setContentsMargins(16, 12, 16, 12)

        self._step_label = QLabel()
        self._step_label.setStyleSheet("color: #9aa4b2; font-size: 11px;")
        panel_layout.addWidget(self._step_label)

        self._title_label = QLabel()
        self._title_label.setStyleSheet("font-weight: bold; font-size: 14px;")
        self._title_label.setWordWrap(True)
        panel_layout.addWidget(self._title_label)

        self._body_label = QLabel()
        self._body_label.setWordWrap(True)
        self._body_label.setMinimumWidth(320)
        self._body_label.setMaximumWidth(420)
        panel_layout.addWidget(self._body_label)

        buttons_row = QHBoxLayout()
        self._skip_button = QPushButton("Saltar tutorial")
        self._skip_button.clicked.connect(self._finish)
        buttons_row.addWidget(self._skip_button)
        buttons_row.addStretch(1)
        self._back_button = QPushButton("Atrás")
        self._back_button.clicked.connect(self._go_back)
        buttons_row.addWidget(self._back_button)
        self._next_button = QPushButton("Siguiente")
        self._next_button.setObjectName("Accent")
        self._next_button.clicked.connect(self._go_next)
        buttons_row.addWidget(self._next_button)
        panel_layout.addLayout(buttons_row)

        self._show_step()

    # -------------------------------------------------------------- navegación
    def _finish(self) -> None:
        self.hide()
        self.deleteLater()
        if self._on_finished is not None:
            self._on_finished()

    def _go_next(self) -> None:
        if self._index >= len(self._steps) - 1:
            self._finish()
            return
        self._index += 1
        self._show_step()

    def _go_back(self) -> None:
        if self._index == 0:
            return
        self._index -= 1
        self._show_step()

    def keyPressEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        if event.key() == Qt.Key.Key_Escape:
            self._finish()
            return
        if event.key() in (Qt.Key.Key_Right, Qt.Key.Key_Return, Qt.Key.Key_Enter):
            self._go_next()
            return
        if event.key() == Qt.Key.Key_Left:
            self._go_back()
            return
        super().keyPressEvent(event)

    # -------------------------------------------------------------- contenido/layout
    def current_step(self) -> TutorialStep:
        return self._steps[self._index]

    def current_step_index(self) -> int:
        return self._index

    def _show_step(self) -> None:
        step = self._steps[self._index]
        self._step_label.setText(f"Paso {self._index + 1} de {len(self._steps)}")
        self._title_label.setText(step.title)

        body_parts = []
        if step.what_it_does:
            body_parts.append(f"<b>QUÉ HACE:</b> {step.what_it_does}")
        if step.when_to_use:
            body_parts.append(f"<b>CUÁNDO USARLO:</b> {step.when_to_use}")
        if step.what_it_needs:
            body_parts.append(f"<b>QUÉ NECESITA:</b> {step.what_it_needs}")
        if step.what_it_produces:
            body_parts.append(f"<b>QUÉ PRODUCE:</b> {step.what_it_produces}")
        self._body_label.setText("<br><br>".join(body_parts))

        self._back_button.setEnabled(self._index > 0)
        self._next_button.setText("Siguiente" if self._index < len(self._steps) - 1 else "Finalizar")

        self.setGeometry(self._main_window.rect())
        self._current_rect = step.target(self._main_window)
        # Un `target` puede tener que elevar una pestaña de dock
        # tabificada (p. ej. CANDIDATOS, tabificado con PROPIEDADES) para
        # que el hueco resaltado corresponda a la pestaña visible -- eso
        # reordena el apilamiento interno de QMainWindow y puede dejar la
        # propia capa del tutorial por DEBAJO del dock recién elevado.
        # Se reafirma aquí, en cada paso, que la capa sigue por encima de
        # todo lo demás.
        self.raise_()
        self._reposition_panel()
        self.update()

    def resizeEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        super().resizeEvent(event)
        self._reposition_panel()

    def _reposition_panel(self) -> None:
        self._panel.adjustSize()
        panel_size = self._panel.sizeHint()
        window_rect = self.rect()
        max_x = max(_PANEL_GAP, window_rect.width() - panel_size.width() - _PANEL_GAP)
        max_y = max(_PANEL_GAP, window_rect.height() - panel_size.height() - _PANEL_GAP)

        if self._current_rect is None:
            x = (window_rect.width() - panel_size.width()) // 2
            y = (window_rect.height() - panel_size.height()) // 2
        else:
            target = self._current_rect
            x = target.right() + _PANEL_GAP
            y = target.top()
            if x > max_x:
                x = target.left() - _PANEL_GAP - panel_size.width()
            if x < _PANEL_GAP:
                x = min(max(target.left(), _PANEL_GAP), max_x)
                y = target.bottom() + _PANEL_GAP
                if y > max_y:
                    y = target.top() - _PANEL_GAP - panel_size.height()

        x = max(_PANEL_GAP, min(x, max_x))
        y = max(_PANEL_GAP, min(y, max_y))
        self._panel.move(x, y)
        self._panel.resize(panel_size)

    def paintEvent(self, event) -> None:  # noqa: N802 -- override de Qt
        painter = QPainter(self)
        if self._current_rect is None:
            painter.fillRect(self.rect(), _DIM_COLOR)
            painter.end()
            return

        # En vez de pintar todo y luego "borrar" el hueco (frágil: solo
        # limpia el buffer de ESTA capa, no revela de verdad el control
        # real que hay detrás cuando la capa está por encima de él en el
        # apilamiento, como ocurre tras elevar una pestaña de dock) --
        # se recorta la región del hueco y NUNCA se pinta ahí: al ser una
        # capa translúcida, lo que no se pinta queda realmente
        # transparente, dejando ver el control real sin trucos de
        # composición.
        hole = self._current_rect.adjusted(-_MARGIN, -_MARGIN, _MARGIN, _MARGIN)
        dim_region = QRegion(self.rect()).subtracted(QRegion(hole))
        painter.setClipRegion(dim_region)
        painter.fillRect(self.rect(), _DIM_COLOR)
        painter.setClipRegion(QRegion(self.rect()))

        pen = painter.pen()
        pen.setColor(_HIGHLIGHT_COLOR)
        pen.setWidth(2)
        painter.setPen(pen)
        painter.drawRect(hole)
        painter.end()
