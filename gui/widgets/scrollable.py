"""Contenedor con scroll vertical -- Tkinter no trae uno nativo; el
patrón estándar es un `Canvas` + `Frame` interior + `Scrollbar`."""
from __future__ import annotations

import tkinter as tk


class ScrollableFrame(tk.Frame):
    def __init__(self, master: tk.Misc, *, background: str):
        super().__init__(master, background=background)
        self.canvas = tk.Canvas(self, background=background, highlightthickness=0)
        self.scrollbar = tk.Scrollbar(self, orient="vertical", command=self.canvas.yview)
        self.body = tk.Frame(self.canvas, background=background)

        self.body.bind("<Configure>", lambda e: self.canvas.configure(scrollregion=self.canvas.bbox("all")))
        self._window = self.canvas.create_window((0, 0), window=self.body, anchor="nw")
        self.canvas.bind("<Configure>", lambda e: self.canvas.itemconfigure(self._window, width=e.width))
        self.canvas.configure(yscrollcommand=self.scrollbar.set)

        self.canvas.pack(side="left", fill="both", expand=True)
        self.scrollbar.pack(side="right", fill="y")

        self.canvas.bind("<Enter>", lambda e: self.canvas.bind_all("<MouseWheel>", self._on_mousewheel))
        self.canvas.bind("<Leave>", lambda e: self.canvas.unbind_all("<MouseWheel>"))

    def _on_mousewheel(self, event: tk.Event) -> None:
        delta = -1 * (event.delta // 120) if event.delta else 0
        self.canvas.yview_scroll(delta, "units")
