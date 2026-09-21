"""Tarjeta con borde de 1px de color exacto -- ttk/clam no permite fijar
el color de borde de un Frame de forma fiable entre plataformas; se usa
`tk.Frame` con `highlightbackground`, el truco estándar de Tk para esto.
"""
from __future__ import annotations

import tkinter as tk

from gui.theme import Palette


class Card(tk.Frame):
    def __init__(self, master: tk.Misc, palette: Palette, *, padding: int = 16):
        super().__init__(
            master,
            background=palette.panel,
            highlightbackground=palette.border,
            highlightcolor=palette.border,
            highlightthickness=1,
            bd=0,
        )
        self.inner = tk.Frame(self, background=palette.panel)
        self.inner.pack(fill="both", expand=True, padx=padding, pady=padding)
