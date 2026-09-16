"""Insignia de estado -- el equivalente Tkinter de los `.badge-*` de la
landing page (píldora redondeada de color semántico + texto). ttk no
soporta esquinas redondeadas de forma nativa; se dibuja con `Canvas`."""
from __future__ import annotations

import tkinter as tk

from gui.theme import Fonts, Palette


class Badge(tk.Canvas):
    def __init__(self, master: tk.Misc, *, text: str, fg: str, bg: str, fonts: Fonts, panel_bg: str):
        self._fonts = fonts
        self._pad_x = 10
        self._pad_y = 5
        font = (fonts.mono, 8, "bold")
        tmp = tk.Label(master, text=text, font=font)
        text_width = tmp.winfo_reqwidth() or (len(text) * 7)
        text_height = tmp.winfo_reqheight() or 14
        tmp.destroy()
        width = text_width + 2 * self._pad_x
        height = text_height + 2 * self._pad_y
        super().__init__(master, width=width, height=height, background=panel_bg, highlightthickness=0)
        self._draw_pill(width, height, bg)
        self.create_text(width / 2, height / 2, text=text.upper(), fill=fg, font=font)

    def _draw_pill(self, width: int, height: int, color: str) -> None:
        radius = height / 2
        self.create_oval(0, 0, height, height, fill=color, outline=color)
        self.create_oval(width - height, 0, width, height, fill=color, outline=color)
        self.create_rectangle(radius, 0, width - radius, height, fill=color, outline=color)
