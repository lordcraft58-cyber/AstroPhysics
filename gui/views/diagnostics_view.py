"""Diagnóstico de equipo -- primer punto de entrada de GUI para
`services.hardware_service.HardwareCheckJob` (ver Fase 1: subsistema
correcto pero, hasta ahora, sin cablear a ningún punto de entrada real).
"""
from __future__ import annotations

import tkinter as tk

from services.hardware_service import HardwareCheckJob
from gui.widgets.card import Card

POLL_MS = 150


class DiagnosticsView(tk.Frame):
    def __init__(self, master: tk.Misc, app):
        self.app = app
        p = app.palette
        super().__init__(master, background=p.bg)
        self._job: HardwareCheckJob | None = None
        self._polling = False

        header = tk.Frame(self, background=p.bg)
        header.pack(fill="x", padx=36, pady=(30, 6))
        tk.Label(header, text="DIAGNÓSTICO", background=p.bg, foreground=p.accent, font=(app.fonts.mono, 9, "bold")).pack(anchor="w")
        tk.Label(header, text="Equipo y compatibilidad", background=p.bg, foreground=p.ink, font=(app.fonts.heading, 20, "bold")).pack(
            anchor="w", pady=(2, 0)
        )

        actions = tk.Frame(self, background=p.bg)
        actions.pack(fill="x", padx=36, pady=(14, 0))
        self.run_button = tk.Button(
            actions, text="Analizar este equipo", relief="flat", bd=0, cursor="hand2",
            background=p.accent, foreground=p.accent_ink, font=(app.fonts.body, 10, "bold"), padx=18, pady=9,
            command=self._run,
        )
        self.run_button.pack(side="left")
        self.status_label = tk.Label(actions, text="", background=p.bg, foreground=p.ink_3, font=(app.fonts.body, 9))
        self.status_label.pack(side="left", padx=(12, 0))

        self.results_container = tk.Frame(self, background=p.bg)
        self.results_container.pack(fill="both", expand=True, padx=36, pady=(20, 24))

    def on_show(self) -> None:
        if self._job is None:
            for widget in self.results_container.winfo_children():
                widget.destroy()
            p = self.app.palette
            empty = Card(self.results_container, p, padding=24)
            empty.pack(fill="x")
            tk.Label(
                empty.inner, text='Pulsa "Analizar este equipo" para comprobar RAM, GPU, disco y cámaras ZWO ASI conectadas.',
                background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 10),
            ).pack(anchor="w")

    def _run(self) -> None:
        self.run_button.configure(state="disabled")
        self.status_label.configure(text="Analizando…")
        self._job = HardwareCheckJob()
        self._job.start()
        self._poll()

    def _poll(self) -> None:
        if self._job is None:
            return
        for event in self._job.poll():
            self.run_button.configure(state="normal")
            self.status_label.configure(text="")
            if event.kind == "done":
                self._render_report(event.report)
            elif event.kind == "error":
                self._render_error(event.error)
            self._job = None
            return
        self.after(POLL_MS, self._poll)

    def _render_error(self, message: str) -> None:
        p = self.app.palette
        for widget in self.results_container.winfo_children():
            widget.destroy()
        card = Card(self.results_container, p, padding=20)
        card.pack(fill="x")
        tk.Label(card.inner, text=f"No se pudo completar el diagnóstico: {message}", background=p.panel, foreground=p.coral, font=(self.app.fonts.body, 10)).pack(
            anchor="w"
        )

    def _render_report(self, report: dict) -> None:
        p = self.app.palette
        for widget in self.results_container.winfo_children():
            widget.destroy()

        stats = tk.Frame(self.results_container, background=p.bg)
        stats.pack(fill="x", pady=(0, 14))
        ram_gb = report.get("ram_gb")
        free_gb = report.get("free_disk_gb")
        self._stat_card(stats, "RAM", f"{ram_gb:.1f} GB" if ram_gb is not None else "—")
        self._stat_card(stats, "Disco libre", f"{free_gb:.0f} GB" if free_gb is not None else "—")
        gpu_names = report.get("gpu_names") or "—"
        self._stat_card(stats, "GPU", gpu_names if len(gpu_names) < 24 else gpu_names[:21] + "…")
        torch_info = report.get("torch", {})
        cuda_text = "CUDA" if torch_info.get("cuda") else ("CPU" if torch_info.get("available") else "no disponible")
        self._stat_card(stats, "AstroVision", cuda_text)

        detail = Card(self.results_container, p, padding=18)
        detail.pack(fill="x", pady=(0, 14))
        asi_detected = report.get("zwo_asi_detected")
        self._kv_row(detail.inner, "Cámara ZWO ASI detectada", "Sí" if asi_detected else "No")
        cpu = report.get("cpu") or {}
        if cpu.get("Name"):
            self._kv_row(detail.inner, "CPU", str(cpu.get("Name")))

        recommendations = report.get("recommendations") or []
        if recommendations:
            rec_card = Card(self.results_container, p, padding=18)
            rec_card.pack(fill="x")
            tk.Label(
                rec_card.inner, text="RECOMENDACIONES", background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 8, "bold")
            ).pack(anchor="w", pady=(0, 6))
            for rec in recommendations:
                tk.Label(
                    rec_card.inner, text=f"·  {rec}", background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 9),
                    anchor="w", justify="left", wraplength=760,
                ).pack(anchor="w", pady=2)

    def _stat_card(self, parent: tk.Frame, label: str, value: str) -> None:
        p = self.app.palette
        card = Card(parent, p, padding=14)
        card.pack(side="left", padx=(0, 12), fill="y")
        tk.Label(card.inner, text=value, background=p.panel, foreground=p.ink, font=(self.app.fonts.heading, 14, "bold")).pack(anchor="w")
        tk.Label(card.inner, text=label.upper(), background=p.panel, foreground=p.ink_3, font=(self.app.fonts.mono, 7, "bold")).pack(
            anchor="w", pady=(2, 0)
        )

    def _kv_row(self, parent: tk.Frame, label: str, value: str) -> None:
        p = self.app.palette
        row = tk.Frame(parent, background=p.panel)
        row.pack(fill="x", pady=3)
        tk.Label(row, text=label, background=p.panel, foreground=p.ink_2, font=(self.app.fonts.body, 9), width=28, anchor="w").pack(
            side="left"
        )
        tk.Label(row, text=value, background=p.panel, foreground=p.ink, font=(self.app.fonts.mono, 9), anchor="w").pack(side="left")
