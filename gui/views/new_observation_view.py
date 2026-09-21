"""Asistente de nueva observación: nombre del objetivo + imágenes con su
banda. Deliberadamente simple -- una sola pantalla, sin pasos ocultos;
las opciones técnicas (umbral, radio de cruce, etc.) viven en
"Configuración avanzada", no aquí.
"""
from __future__ import annotations

import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

BAND_OPTIONS = ["OIII", "HA", "NII", "SII", "BROADBAND", "L-QEF", "OTRA"]


class NewObservationView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)
        self._image_rows: list[dict] = []

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 10))
        tk.Label(header, text="NUEVA OBSERVACIÓN", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(
            anchor="w"
        )
        tk.Label(header, text="Cargar imágenes", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold")).pack(
            anchor="w", pady=(2, 0)
        )

        form = tk.Frame(self, background=p.bg)
        form.pack(fill="x", padx=36, pady=(10, 0))
        tk.Label(form, text="Nombre del objetivo", background=p.bg, foreground=p.ink_2, font=(app.fonts.body, 9)).pack(anchor="w")
        self.target_entry = tk.Entry(
            form, font=(app.fonts.body, 11), background=p.panel, foreground=p.ink, relief="solid", bd=1,
            highlightbackground=p.border, highlightcolor=p.accent,
        )
        self.target_entry.pack(fill="x", ipady=6, pady=(4, 16))

        images_header = tk.Frame(self, background=p.bg)
        images_header.pack(fill="x", padx=36)
        tk.Label(images_header, text="Imágenes", background=p.bg, foreground=p.ink_2, font=(app.fonts.body, 9)).pack(side="left")
        tk.Button(
            images_header, text="+ Añadir imagen…", relief="flat", bd=0, cursor="hand2",
            background=p.bg, foreground=p.accent, font=(app.fonts.body, 9, "bold"),
            command=self._add_images,
        ).pack(side="right")

        self.rows_container = tk.Frame(self, background=p.bg)
        self.rows_container.pack(fill="both", expand=True, padx=36, pady=(8, 0))

        footer = tk.Frame(self, background=p.bg)
        footer.pack(fill="x", padx=36, pady=20)
        self.analyze_button = tk.Button(
            footer, text="Analizar", relief="flat", bd=0, cursor="hand2",
            background=p.accent, foreground=p.accent_ink, font=(app.fonts.body, 11, "bold"), padx=22, pady=10,
            command=self._start_analysis, state="disabled",
        )
        self.analyze_button.pack(side="left")
        self.status_label = tk.Label(footer, text="", background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 9))
        self.status_label.pack(side="left", padx=(12, 0))

    def on_show(self) -> None:
        pass

    def _add_images(self) -> None:
        paths = filedialog.askopenfilenames(
            title="Seleccionar imágenes", filetypes=[("FITS", "*.fits *.fit *.fts"), ("Todos los archivos", "*.*")]
        )
        for path in paths:
            self._add_row(path)
        self._refresh_state()

    def _add_row(self, path: str) -> None:
        p = self.app.palette
        row = tk.Frame(self.rows_container, background=p.panel_2)
        row.pack(fill="x", pady=2)
        tk.Label(row, text=Path(path).name, background=p.panel_2, foreground=p.ink, font=(self.app.fonts.mono, 9)).pack(
            side="left", padx=(10, 8), pady=6
        )
        band_var = tk.StringVar(value=BAND_OPTIONS[0])
        combo = ttk.Combobox(row, textvariable=band_var, values=BAND_OPTIONS, width=12, state="readonly")
        combo.pack(side="left", padx=4)
        record = {"path": path, "band_var": band_var, "row": row}

        def remove():
            row.destroy()
            self._image_rows.remove(record)
            self._refresh_state()

        tk.Button(
            row, text="✕", relief="flat", bd=0, background=p.panel_2, foreground=p.coral, cursor="hand2", command=remove
        ).pack(side="right", padx=8)
        self._image_rows.append(record)

    def _refresh_state(self) -> None:
        self.analyze_button.configure(state="normal" if self._image_rows else "disabled")

    def _start_analysis(self) -> None:
        target_name = self.target_entry.get().strip()
        if not target_name:
            messagebox.showwarning(self.app.root.title(), "Indica un nombre de objetivo antes de analizar.")
            return
        images = [(record["path"], record["band_var"].get()) for record in self._image_rows]
        self.app.start_analysis(target_name=target_name, images=images)

        for record in self._image_rows:
            record["row"].destroy()
        self._image_rows.clear()
        self.target_entry.delete(0, tk.END)
        self._refresh_state()
