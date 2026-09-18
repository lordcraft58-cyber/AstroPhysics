"""Lenguaje visual de la GUI -- traducido, no copiado, de la landing page
comercial (paleta ámbar/cian/coral/índigo sobre fondo neutro, tipografía
geométrica para títulos + monoespaciada para datos). Tkinter no puede
reproducir sombras CSS ni gradientes; lo que sí se traslada fielmente es
la paleta de color y la lógica semántica de los badges de estado -- ver
docs/audit/10-FASE8-GUI.md.
"""
from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from dataclasses import dataclass
from tkinter import ttk


@dataclass(frozen=True)
class Palette:
    bg: str
    bg_hero: str
    panel: str
    panel_2: str
    border: str
    ink: str
    ink_2: str
    ink_3: str
    accent: str
    accent_ink: str
    accent_soft: str
    cyan: str
    cyan_soft: str
    coral: str
    coral_soft: str
    indigo: str
    indigo_soft: str


LIGHT = Palette(
    bg="#f3f5fb", bg_hero="#eef1f9", panel="#ffffff", panel_2="#eef1f9", border="#d7deee",
    ink="#10182b", ink_2="#4c5876", ink_3="#7c88a6",
    accent="#b3790a", accent_ink="#1a1206", accent_soft="#fbead0",
    cyan="#0f8f86", cyan_soft="#dff4f1",
    coral="#c23f5a", coral_soft="#fbe3e8",
    indigo="#5b5fc7", indigo_soft="#e6e6fb",
)

DARK = Palette(
    bg="#090c14", bg_hero="#0b0f1c", panel="#11172a", panel_2="#161d34", border="#232c49",
    ink="#edf0f9", ink_2="#aab4d1", ink_3="#79839f",
    accent="#f0b429", accent_ink="#1a1206", accent_soft="#3a2d0d",
    cyan="#5fd9cc", cyan_soft="#0f2b28",
    coral="#ff7a90", coral_soft="#3a1620",
    indigo="#9599f2", indigo_soft="#232351",
)

# Estados -> color semántico. Un único lugar que traduce el vocabulario
# de IdentificationState (Fase 4) al lenguaje visual -- si el vocabulario
# cambia, solo hay que tocar aquí.
STATE_COLOR_KEY = {
    "KNOWN": "cyan",
    "KNOWN_VARIANT": "cyan",
    "UNMATCHED": "accent",
    "ANOMALOUS": "coral",
    "TRANSIENT_CANDIDATE": "coral",
    "MOVING_SOURCE_CANDIDATE": "indigo",
    "DISCOVERY_REVIEW": "accent",
}
STATE_LABEL_ES = {
    "KNOWN": "Conocido",
    "KNOWN_VARIANT": "Conocido (variante)",
    "UNMATCHED": "No asociado",
    "ANOMALOUS": "Anomalía",
    "TRANSIENT_CANDIDATE": "Transitorio",
    "MOVING_SOURCE_CANDIDATE": "Movimiento",
    "DISCOVERY_REVIEW": "Requiere revisión",
}

REVIEW_COLOR_KEY = {"PENDING": "ink_3", "KEPT": "cyan", "REJECTED": "coral", "FLAGGED": "accent"}
REVIEW_LABEL_ES = {"PENDING": "Pendiente", "KEPT": "Conservado", "REJECTED": "Descartado", "FLAGGED": "Marcado"}

QUALITY_COLOR_KEY = {"PASS": "cyan", "WARNING": "accent", "FAIL": "coral", "NOT_AVAILABLE": "ink_3"}


def color_for(palette: Palette, key: str) -> str:
    return getattr(palette, key)


def _first_available_family(preferred: list[str]) -> str:
    available = set(tkfont.families())
    for name in preferred:
        if name in available:
            return name
    return preferred[-1]  # última entrada: siempre una familia genérica de Tk


@dataclass(frozen=True)
class Fonts:
    heading: str
    body: str
    mono: str


def resolve_fonts() -> Fonts:
    """Segoe UI / Consolas (Windows) se acercan en espíritu a Unbounded/
    Manrope/IBM Plex Mono de la landing page sin depender de bundlear
    tipografías web -- con caída a las familias genéricas de Tk en
    cualquier sistema donde no estén instaladas (como este entorno de
    desarrollo Linux)."""
    return Fonts(
        heading=_first_available_family(["Segoe UI Semibold", "Segoe UI", "Helvetica", "TkDefaultFont"]),
        body=_first_available_family(["Segoe UI", "Helvetica", "TkDefaultFont"]),
        mono=_first_available_family(["Cascadia Mono", "Consolas", "DejaVu Sans Mono", "TkFixedFont"]),
    )


def apply_theme(root: tk.Misc, palette: Palette) -> Fonts:
    """Configura ttk (tema 'clam', el único de los integrados con control
    real de color en todas las plataformas) con los estilos que las
    vistas reutilizan. Devuelve las fuentes resueltas para que las vistas
    las usen también en widgets que no son ttk (p. ej. `tk.Canvas`)."""
    fonts = resolve_fonts()
    style = ttk.Style(root)
    style.theme_use("clam")

    root.configure(background=palette.bg)

    style.configure(".", background=palette.bg, foreground=palette.ink, font=(fonts.body, 10))
    style.configure("TFrame", background=palette.bg)
    style.configure("Panel.TFrame", background=palette.panel)
    style.configure("Sidebar.TFrame", background=palette.bg_hero)

    style.configure("TLabel", background=palette.bg, foreground=palette.ink, font=(fonts.body, 10))
    style.configure("Panel.TLabel", background=palette.panel, foreground=palette.ink, font=(fonts.body, 10))
    style.configure("Heading.TLabel", background=palette.bg, foreground=palette.ink, font=(fonts.heading, 18, "bold"))
    style.configure("PanelHeading.TLabel", background=palette.panel, foreground=palette.ink, font=(fonts.heading, 13, "bold"))
    style.configure("Muted.TLabel", background=palette.bg, foreground=palette.ink_2, font=(fonts.body, 10))
    style.configure("PanelMuted.TLabel", background=palette.panel, foreground=palette.ink_2, font=(fonts.body, 10))
    style.configure("Eyebrow.TLabel", background=palette.bg, foreground=palette.accent, font=(fonts.mono, 9, "bold"))
    style.configure("Mono.TLabel", background=palette.panel, foreground=palette.ink, font=(fonts.mono, 10))

    style.configure(
        "Accent.TButton", background=palette.accent, foreground=palette.accent_ink, font=(fonts.body, 10, "bold"),
        padding=(16, 9), borderwidth=0,
    )
    style.map("Accent.TButton", background=[("active", palette.accent), ("disabled", palette.border)])
    style.configure(
        "Ghost.TButton", background=palette.bg, foreground=palette.ink, font=(fonts.body, 10),
        padding=(14, 8), borderwidth=1, relief="solid", bordercolor=palette.border,
    )
    style.map("Ghost.TButton", background=[("active", palette.panel_2)])

    style.configure(
        "Nav.TButton", background=palette.bg_hero, foreground=palette.ink_2, font=(fonts.body, 10, "bold"),
        padding=(14, 10), borderwidth=0, anchor="w",
    )
    style.map(
        "Nav.TButton",
        background=[("active", palette.panel_2)],
        foreground=[("active", palette.ink)],
    )
    style.configure(
        "NavSelected.TButton", background=palette.panel_2, foreground=palette.accent, font=(fonts.body, 10, "bold"),
        padding=(14, 10), borderwidth=0, anchor="w",
    )

    style.configure(
        "Treeview", background=palette.panel, fieldbackground=palette.panel, foreground=palette.ink,
        rowheight=30, font=(fonts.body, 10), borderwidth=0,
    )
    style.configure("Treeview.Heading", background=palette.panel_2, foreground=palette.ink_2, font=(fonts.mono, 8, "bold"), relief="flat")
    style.map("Treeview", background=[("selected", palette.accent_soft)], foreground=[("selected", palette.ink)])

    style.configure("TProgressbar", background=palette.accent, troughcolor=palette.panel_2, borderwidth=0)
    style.configure("TEntry", fieldbackground=palette.panel, foreground=palette.ink, bordercolor=palette.border)
    style.configure("TCombobox", fieldbackground=palette.panel, background=palette.panel, foreground=palette.ink)
    style.configure("TSeparator", background=palette.border)

    return fonts
