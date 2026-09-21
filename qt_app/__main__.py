"""Punto de entrada del taller: `python -m qt_app`."""
from __future__ import annotations

import logging
import sys

from PySide6.QtWidgets import QApplication

from qt_app.main_window import MainWindow


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    app = QApplication(sys.argv)
    app.setApplicationName("AstroPhysics Suite")
    window = MainWindow()
    window.show()
    window.maybe_show_tutorial_on_startup()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
