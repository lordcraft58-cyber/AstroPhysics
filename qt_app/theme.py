"""Lenguaje visual del taller -- tema oscuro profesional de baja
saturación (pensado para minimizar fatiga visual durante sesiones largas
de reducción/análisis, igual que PixInsight/la mayoría del software de
procesamiento astrofotográfico serio) más la hoja de estilos Qt (QSS)
que lo aplica.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Palette:
    bg: str
    bg_elevated: str
    bg_panel: str
    bg_input: str
    border: str
    border_strong: str
    ink: str
    ink_muted: str
    ink_faint: str
    accent: str
    accent_ink: str
    cyan: str
    amber: str
    coral: str
    indigo: str


DARK = Palette(
    bg="#242427",
    bg_elevated="#2c2c30",
    bg_panel="#323238",
    bg_input="#1c1c1f",
    border="#3c3c42",
    border_strong="#4a4a52",
    ink="#e4e4e8",
    ink_muted="#9c9ca6",
    ink_faint="#6a6a72",
    accent="#4a9edb",
    accent_ink="#0c1620",
    cyan="#4fc9b0",
    amber="#d9a441",
    coral="#d9707a",
    indigo="#8f8fe0",
)


def build_stylesheet(p: Palette) -> str:
    return f"""
    QMainWindow, QWidget {{
        background: {p.bg};
        color: {p.ink};
        font-size: 12px;
    }}
    QMdiArea {{
        background: {p.bg_input};
    }}
    QMenuBar {{
        background: {p.bg_elevated};
        border-bottom: 1px solid {p.border};
        padding: 2px;
    }}
    QMenuBar::item:selected {{
        background: {p.bg_panel};
        border-radius: 3px;
    }}
    QMenu {{
        background: {p.bg_elevated};
        border: 1px solid {p.border};
    }}
    QMenu::item:selected {{
        background: {p.accent};
        color: {p.accent_ink};
    }}
    QToolBar {{
        background: {p.bg_elevated};
        border-bottom: 1px solid {p.border};
        spacing: 4px;
        padding: 3px;
    }}
    QDockWidget {{
        color: {p.ink_muted};
        titlebar-close-icon: none;
    }}
    QDockWidget::title {{
        background: {p.bg_elevated};
        padding: 5px 8px;
        border-bottom: 1px solid {p.border};
        font-weight: 600;
        font-size: 10px;
    }}
    QTreeWidget, QListWidget {{
        background: {p.bg_panel};
        border: 1px solid {p.border};
        alternate-background-color: {p.bg_elevated};
    }}
    QTreeWidget::item, QListWidget::item {{
        padding: 3px;
    }}
    QTreeWidget::item:selected, QListWidget::item:selected {{
        background: {p.accent};
        color: {p.accent_ink};
    }}
    QHeaderView::section {{
        background: {p.bg_elevated};
        border: none;
        border-bottom: 1px solid {p.border};
        padding: 4px;
        color: {p.ink_muted};
    }}
    QPlainTextEdit, QTextEdit {{
        background: {p.bg_input};
        border: 1px solid {p.border};
        color: {p.ink};
        font-family: "Cascadia Mono", "Consolas", "DejaVu Sans Mono", monospace;
        font-size: 11px;
    }}
    QPushButton {{
        background: {p.bg_panel};
        border: 1px solid {p.border_strong};
        border-radius: 3px;
        padding: 5px 12px;
    }}
    QPushButton:hover {{
        background: {p.border_strong};
    }}
    QPushButton:pressed {{
        background: {p.border};
    }}
    QPushButton#Accent {{
        background: {p.accent};
        color: {p.accent_ink};
        border: none;
        font-weight: 600;
    }}
    QPushButton#Accent:hover {{
        background: #5aabe6;
    }}
    QPushButton:disabled {{
        color: {p.ink_faint};
        border-color: {p.border};
    }}
    QLabel#Eyebrow {{
        color: {p.accent};
        font-weight: 700;
        font-size: 9px;
        letter-spacing: 1px;
    }}
    QLabel#SectionHeading {{
        color: {p.ink};
        font-weight: 700;
        font-size: 13px;
    }}
    QLabel#Muted {{
        color: {p.ink_muted};
    }}
    QDoubleSpinBox, QSpinBox, QComboBox, QLineEdit {{
        background: {p.bg_input};
        border: 1px solid {p.border_strong};
        border-radius: 3px;
        padding: 3px 6px;
        color: {p.ink};
    }}
    QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QLineEdit:focus {{
        border-color: {p.accent};
    }}
    QMdiSubWindow {{
        background: {p.bg_panel};
        border: 1px solid {p.border};
    }}
    QStatusBar {{
        background: {p.bg_elevated};
        border-top: 1px solid {p.border};
        color: {p.ink_muted};
    }}
    QScrollBar:vertical {{
        background: {p.bg_panel};
        width: 12px;
    }}
    QScrollBar::handle:vertical {{
        background: {p.border_strong};
        min-height: 24px;
        border-radius: 5px;
    }}
    QSplitter::handle {{
        background: {p.border};
    }}
    QProgressBar {{
        background: {p.bg_input};
        border: 1px solid {p.border};
        border-radius: 3px;
        text-align: center;
        color: {p.ink};
    }}
    QProgressBar::chunk {{
        background: {p.accent};
        border-radius: 2px;
    }}
    """
