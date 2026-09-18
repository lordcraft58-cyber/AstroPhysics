"""Ajuste de WCS real desde estrellas marcadas a clic -- equivalente
propio de `ccmap`/`ccsetwcs` de IRAF, sobre
`astrophysics_suite.astrometry.wcs_fit.fit_wcs` sin ningún cambio. No hay
resolución automática ("blind plate solving"): el usuario aporta la
posición celeste de cada estrella marcada -- exactamente lo que pedía el
`ccmap` interactivo clásico -- el taller nunca adivina qué estrella es
cuál ni inventa coordenadas.
"""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QHeaderView,
    QLabel,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.astrometry.wcs_fit import fit_wcs
from astrophysics_suite.tables.table import Table


class WCSFitDialog(QDialog):
    fitted = Signal(object, object)
    """Emite `(WCSSolution, Table)` al ajustar con éxito -- la tabla trae
    una fila por estrella (x, y, RA, Dec, residuo en arcosegundos) lista
    para exportar."""

    def __init__(self, points: list[tuple[float, float]], image_shape: tuple[int, int], parent=None):
        super().__init__(parent)
        self._points = points
        height, width = image_shape
        self._crpix_px = (width / 2.0, height / 2.0)
        self.setWindowTitle("Ajustar WCS")
        self.resize(480, 340)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Introduce la ascensión recta y declinación (en grados) de cada estrella "
            "marcada -- el taller no las adivina, consulta un catálogo o un mapa celeste."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.table = QTableWidget(len(points), 4, self)
        self.table.setHorizontalHeaderLabels(["x (px)", "y (px)", "RA (grados)", "Dec (grados)"])
        for row, (x, y) in enumerate(points):
            x_item = QTableWidgetItem(f"{x:.2f}")
            x_item.setFlags(x_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            y_item = QTableWidgetItem(f"{y:.2f}")
            y_item.setFlags(y_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, x_item)
            self.table.setItem(row, 1, y_item)
            self.table.setItem(row, 2, QTableWidgetItem(""))
            self.table.setItem(row, 3, QTableWidgetItem(""))
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.fit_button = self.button_box.addButton("Ajustar WCS", QDialogButtonBox.ButtonRole.AcceptRole)
        self.fit_button.clicked.connect(self._on_fit)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_fit(self) -> None:
        sky_radec: list[tuple[float, float]] = []
        for row in range(self.table.rowCount()):
            ra_item = self.table.item(row, 2)
            dec_item = self.table.item(row, 3)
            ra_text = ra_item.text().strip() if ra_item else ""
            dec_text = dec_item.text().strip() if dec_item else ""
            if not ra_text or not dec_text:
                self.status_label.setText(f"Falta RA/Dec en la fila {row + 1}.")
                return
            try:
                sky_radec.append((float(ra_text), float(dec_text)))
            except ValueError:
                self.status_label.setText(f"RA/Dec no numéricos en la fila {row + 1}.")
                return

        # El ajuste opera solo sobre las N posiciones marcadas (mínimos
        # cuadrados de unas pocas decenas de puntos como mucho), nunca
        # sobre la imagen completa -- no hace falta hilo de fondo.
        try:
            solution = fit_wcs(self._points, sky_radec, crpix_px=self._crpix_px)
        except ValueError as exc:
            self.status_label.setText(f"Error: {exc}")
            return

        self.status_label.setText(f"WCS ajustado: RMS={solution.rms_residual_arcsec:.3f}\" con {solution.n_stars} estrella(s).")
        table = Table(
            columns=("star", "x", "y", "ra", "dec", "residual"),
            units=("", "px", "px", "deg", "deg", "arcsec"),
            rows=tuple(
                (i + 1, x, y, ra, dec, residual)
                for i, ((x, y), (ra, dec), residual) in enumerate(zip(self._points, sky_radec, solution.residuals_arcsec))
            ),
        )
        self.fitted.emit(solution, table)
        self.accept()
