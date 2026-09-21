"""Progreso de un análisis en curso -- consume `services.discovery_
service.DiscoveryJob` sondeándolo desde el hilo principal vía
`after()`, nunca bloqueando. El registro detallado está oculto por
defecto pero disponible con un clic (la Fase 5 encontró que la GUI
heredada no mostraba ningún registro; aquí se corrige desde el diseño).
"""
from __future__ import annotations

import tkinter as tk
from tkinter import ttk


class AnalysisView(tk.Frame):
    POLL_MS = 100

    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)
        self._polling = False
        self._log_visible = False

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 10))
        tk.Label(header, text="ANÁLISIS", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(anchor="w")
        self.target_label = tk.Label(header, text="", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold"))
        self.target_label.pack(anchor="w", pady=(2, 0))

        body = tk.Frame(self, background=p.bg)
        body.pack(fill="x", padx=36, pady=(20, 0))

        self.progress = ttk.Progressbar(body, style="TProgressbar", mode="determinate", maximum=100, length=520)
        self.progress.pack(anchor="w")
        self.status_label = tk.Label(body, text="", background=p.bg, foreground=p.ink_2, font=(app.fonts.body, 10))
        self.status_label.pack(anchor="w", pady=(10, 0))

        actions = tk.Frame(body, background=p.bg)
        actions.pack(anchor="w", pady=(18, 0))
        self.cancel_button = tk.Button(
            actions, text="Cancelar", relief="flat", bd=0, cursor="hand2",
            background=p.bg, foreground=p.coral, font=(app.fonts.body, 9, "bold"),
            command=self._cancel,
        )
        self.cancel_button.pack(side="left")
        self.log_toggle = tk.Button(
            actions, text="Mostrar registro", relief="flat", bd=0, cursor="hand2",
            background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 9),
            command=self._toggle_log,
        )
        self.log_toggle.pack(side="left", padx=(16, 0))

        self.log_frame = tk.Frame(self, background=p.panel, highlightbackground=p.border, highlightthickness=1)
        self.log_text = tk.Text(
            self.log_frame, height=10, background=p.panel, foreground=p.ink_2, font=(app.fonts.mono, 9),
            relief="flat", state="disabled", wrap="word",
        )
        self.log_text.pack(fill="both", expand=True, padx=10, pady=10)

    def on_show(self) -> None:
        job = self.app.active_job
        self.target_label.configure(text=getattr(job, "_target_name", ""))
        self.progress["value"] = 0
        self.status_label.configure(text="Iniciando…")
        self.cancel_button.configure(state="normal")
        self._start_polling()

    def _toggle_log(self) -> None:
        self._log_visible = not self._log_visible
        if self._log_visible:
            self.log_frame.pack(fill="both", expand=True, padx=36, pady=(20, 20))
            self.log_toggle.configure(text="Ocultar registro")
        else:
            self.log_frame.pack_forget()
            self.log_toggle.configure(text="Mostrar registro")

    def _cancel(self) -> None:
        if self.app.active_job is not None:
            self.app.active_job.cancel()
        self.cancel_button.configure(state="disabled")

    def _append_log(self, lines: list[str]) -> None:
        if not lines:
            return
        self.log_text.configure(state="normal")
        for line in lines:
            self.log_text.insert("end", line + "\n")
        self.log_text.see("end")
        self.log_text.configure(state="disabled")

    def _start_polling(self) -> None:
        if self._polling:
            return
        self._polling = True
        self._poll()

    def _poll(self) -> None:
        self._append_log(self.app.log_bridge.drain())
        job = self.app.active_job
        if job is None:
            self._polling = False
            return

        for event in job.poll():
            if event.kind == "progress":
                self.progress["value"] = event.fraction * 100
                self.status_label.configure(text=event.message)
            elif event.kind == "done":
                self.progress["value"] = 100
                self.status_label.configure(text=f"Completado: {event.summary.n_candidates} candidatos de {event.summary.n_detected} detecciones.")
                self.app.state.add_observation(event.observation, event.loaded_images)
                self.app.state.add_candidates(list(event.candidates))
                self.cancel_button.configure(state="disabled")
                self._polling = False
                self.after(600, lambda: self.app.show_view("candidates"))
                return
            elif event.kind == "cancelled":
                self.status_label.configure(text=event.message or "Análisis cancelado.")
                self.cancel_button.configure(state="disabled")
                self._polling = False
                return
            elif event.kind == "error":
                self.status_label.configure(text=f"Error: {event.message}")
                self.cancel_button.configure(state="disabled")
                self._polling = False
                return

        if self._polling:
            self.after(self.POLL_MS, self._poll)
