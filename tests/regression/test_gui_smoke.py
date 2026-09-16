"""Prueba de humo de GUI: la ventana debe construirse sin excepción.

Contexto: antes de esta fase, NADA ejecutaba nunca `launch_gui()` --
ni un humano lo había vuelto a arrancar recientemente en este entorno, ni
ningún test. Al escribir este test se descubrió que **la GUI activa no
arrancaba en absoluto**: `v["discovery_snr"]` y `v["discovery_max"]` se
leían en dos sitios (el panel "Discovery Workspace" y su worker de
escaneo) pero nunca se inicializaban en el diccionario `v` de variables
Tkinter -- `KeyError` inmediato al construir la barra de controles del
Discovery Workspace, antes de que la ventana llegara a mostrarse. Se
corrigió añadiendo las dos claves faltantes (ver el diff de esta fase).
Es un hallazgo más severo que el P0 de la Fase 1 (que solo afectaba a
Python <3.12): este rompía el arranque en CUALQUIER versión de Python.

Requiere tkinter y un display X (real o Xvfb) -- si no están disponibles
en el entorno, el test se salta explícitamente en vez de fallar por una
razón ajena al código bajo prueba.
"""
from __future__ import annotations

import pytest

tk = pytest.importorskip("tkinter", reason="tkinter no instalado en este entorno")


def _display_available() -> bool:
    try:
        root = tk.Tk()
    except tk.TclError:
        return False
    root.destroy()
    return True


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb)")


def test_launch_gui_builds_without_exception(aps, monkeypatch):
    """Construye la ventana completa (todas las pestañas, todos los
    controles) y confirma que llega a `root.mainloop()` sin lanzar. No
    interactúa con la interfaz -- eso es trabajo de un test de
    integración de GUI más caro, fuera del alcance de un smoke test."""
    mainloop_calls = []

    def fake_mainloop(self, *args, **kwargs):
        mainloop_calls.append(self)
        self.destroy()

    monkeypatch.setattr(tk.Tk, "mainloop", fake_mainloop)

    aps.launch_gui()  # no debe lanzar ninguna excepción

    assert len(mainloop_calls) == 1, "launch_gui debe construir exactamente una ventana raíz y llegar a mainloop()"


def test_launch_gui_is_the_only_public_gui_entry_point(aps):
    """Guarda de arquitectura: no debe volver a existir una segunda
    función launch_gui_* que construya una ventana completa (ver la
    limpieza de launch_gui_legacy en la Fase 3)."""
    import inspect

    gui_launchers = [
        name
        for name, obj in vars(aps).items()
        if inspect.isfunction(obj) and name.startswith("launch_gui") and inspect.getmodule(obj) is aps
    ]
    assert gui_launchers == ["launch_gui"], f"Debe existir exactamente un lanzador de GUI público; encontrados: {gui_launchers}"
