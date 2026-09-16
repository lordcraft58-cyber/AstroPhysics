"""Resolución astrométrica automática -- ver
`astrophysics_suite.astrometry.plate_solve` para el motor real y el
alcance exacto (requiere una posición/escala aproximadas, no es "blind
solving" completo). Este diálogo pide esos valores aproximados
(pre-rellenados desde el header FITS cuando están, editables siempre),
resuelve en un hilo de fondo (consulta Gaia real + búsqueda de
orientación, puede tardar varios segundos), y muestra el resultado con
mensajes accionables -- nunca "Error" a secas."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QVBoxLayout,
)

from astrophysics_suite.astrometry.plate_solve import (
    estimate_approx_pointing_from_header,
    estimate_approx_scale_from_header,
    solve_plate,
)
from astrophysics_suite.tables.table import Table
from qt_app.workers import CallableWorker


class PlateSolveDialog(QDialog):
    """A diferencia de `WCSFitDialog` (que emite `fitted` al aceptar),
    este diálogo expone el resultado vía `result_solution()`/
    `result_table()` después de `exec()` -- mismo patrón que
    `StarPairConfigDialog` (Fase 18): el resultado depende de una
    operación de fondo (`solve_plate`, con red real), así que "aceptar"
    solo tiene sentido una vez que ya se resolvió con éxito."""

    def __init__(self, data, header: dict | None, parent=None):
        super().__init__(parent)
        self._data = data
        self._header = header or {}
        self._worker: CallableWorker | None = None
        self._result_solution = None
        self._result_table: Table | None = None

        self.setWindowTitle("Resolver placa automáticamente")
        self.resize(460, 260)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Detecta estrellas reales y las empareja contra Gaia DR3 a partir de una posición y escala "
            "APROXIMADAS -- no es una resolución \"a ciegas\" completa (ver documentación); si el header "
            "del FITS trae RA/DEC u OBJCTRA/OBJCTDEC y FOCALLEN+XPIXSZ o PIXSCALE, se rellenan solos."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        approx_pointing = estimate_approx_pointing_from_header(self._header)
        approx_scale = estimate_approx_scale_from_header(self._header)

        form = QFormLayout()
        self.ra_spin = QDoubleSpinBox()
        self.ra_spin.setRange(0.0, 359.999999)
        self.ra_spin.setDecimals(6)
        self.ra_spin.setSuffix(" °")
        self.dec_spin = QDoubleSpinBox()
        self.dec_spin.setRange(-90.0, 90.0)
        self.dec_spin.setDecimals(6)
        self.dec_spin.setSuffix(" °")
        self.scale_spin = QDoubleSpinBox()
        self.scale_spin.setRange(0.001, 60.0)
        self.scale_spin.setDecimals(4)
        self.scale_spin.setSuffix(" \"/px")

        if approx_pointing is not None:
            self.ra_spin.setValue(approx_pointing[0])
            self.dec_spin.setValue(approx_pointing[1])
            pointing_source = "del header FITS"
        else:
            pointing_source = "no encontrada en el header -- introduce un valor aproximado"
        if approx_scale is not None:
            self.scale_spin.setValue(approx_scale)
            scale_source = "del header FITS"
        else:
            self.scale_spin.setValue(1.0)
            scale_source = "no encontrada en el header -- introduce un valor aproximado"

        form.addRow("RA aproximada", self.ra_spin)
        form.addRow("Dec aproximada", self.dec_spin)
        form.addRow("Escala aproximada", self.scale_spin)
        layout.addLayout(form)

        self.pointing_hint_label = QLabel(f"Posición: {pointing_source}")
        self.pointing_hint_label.setObjectName("Muted")
        layout.addWidget(self.pointing_hint_label)
        self.scale_hint_label = QLabel(f"Escala: {scale_source}")
        self.scale_hint_label.setObjectName("Muted")
        layout.addWidget(self.scale_hint_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.solve_button = self.button_box.addButton("Resolver", QDialogButtonBox.ButtonRole.ActionRole)
        self.solve_button.clicked.connect(self._on_solve)
        self.accept_button = self.button_box.addButton("Aceptar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_solve(self) -> None:
        self.solve_button.setEnabled(False)
        self.accept_button.setEnabled(False)
        self.status_label.setText("Resolviendo -- detectando estrellas y consultando Gaia...")

        ra0, dec0, scale = self.ra_spin.value(), self.dec_spin.value(), self.scale_spin.value()
        data, header = self._data, self._header

        def run():
            return solve_plate(data, header, approx_ra_deg=ra0, approx_dec_deg=dec0, approx_scale_arcsec_px=scale)

        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_solved)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_solved(self, result) -> None:
        self.solve_button.setEnabled(True)
        if not result.success:
            self.status_label.setText(
                f"PLATE SOLVING FALLIDO: {result.reason}\n\n"
                f"Qué puedes hacer: ajusta la posición/escala aproximada e inténtalo de nuevo, "
                f"o usa \"Ajustar WCS (clic + coordenadas)...\" como alternativa manual."
            )
            return

        self.status_label.setText(
            f"WCS RESUELTO Y VALIDADO -- {result.reason}\n"
            f"Proveedor: {result.provider}\n"
            f"{result.n_detected_stars} estrella(s) detectada(s), {result.n_catalog_stars} en el catálogo, "
            f"{result.n_matched} emparejada(s). Rotación={result.rotation_deg:.2f}°"
            f"{' (espejo)' if result.mirrored else ''}."
        )
        self._result_solution = result.solution
        self._result_table = Table(
            columns=("residual",), units=("arcsec",), rows=tuple((r,) for r in result.solution.residuals_arcsec)
        )
        self.accept_button.setEnabled(True)

    def _on_failed(self, message: str) -> None:
        self.solve_button.setEnabled(True)
        self.status_label.setText(f"PLATE SOLVING FALLIDO: error interno inesperado -- {message}")

    def _on_accept(self) -> None:
        if self._result_solution is None:
            return
        self.accept()

    def result_solution(self):
        return self._result_solution

    def result_table(self) -> Table | None:
        return self._result_table
