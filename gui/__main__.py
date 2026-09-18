"""Punto de entrada de la GUI comercial: `python -m gui`."""
from __future__ import annotations

import tkinter as tk

from gui.app import App


def main() -> None:
    root = tk.Tk()
    App(root)
    root.mainloop()


if __name__ == "__main__":
    main()
