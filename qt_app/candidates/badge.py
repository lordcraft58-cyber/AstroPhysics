"""Insignia de estado -- mucho más simple en Qt que en Tkinter (Fase 8
necesitaba dibujar la píldora a mano en un `Canvas`; Qt soporta
`border-radius` de forma nativa en la hoja de estilos de cualquier
`QLabel`)."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel


class Badge(QLabel):
    def __init__(self, text: str, *, fg: str, bg: str, parent=None):
        super().__init__(text.upper(), parent)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setStyleSheet(
            f"""
            QLabel {{
                background: {bg};
                color: {fg};
                border-radius: 8px;
                padding: 2px 9px;
                font-size: 9px;
                font-weight: 700;
            }}
            """
        )
