"""Resolución astrométrica CIEGA -- ver
`astrophysics_suite.astrometry.blind_solve` para el motor real. A
diferencia de `PlateSolveDialog`, este diálogo no pide ninguna posición
ni escala aproximada: empareja asterismos reales contra lo que ya haya
en la caché local de catálogos (`Catálogos -> Gestionar caché local...`)
y, si encuentra una correspondencia real, delega la verificación final
en el mismo motor con puntero (`plate_solve.solve_plate`). Mismo patrón
de resultado diferido que `PlateSolveDialog`: expone `result_solution()`/
`result_table()` después de `exec()`.
"""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QLabel,
    QVBoxLayout,
)

from astrophysics_suite.astrometry.blind_solve import solve_plate_blind
from astrophysics_suite.catalogs.local_cache import CatalogCache
from astrophysics_suite.tables.table import Table
from qt_app.workers import CallableWorker


class BlindPlateSolveDialog(QDialog):
    def __init__(self, data, header: dict | None, parent=None):
        super().__init__(parent)
        self._data = data
        self._header = header or {}
        self._worker: CallableWorker | None = None
        self._result_solution = None
        self._result_table: Table | None = None

        self.setWindowTitle("Resolver placa en ciego (sin puntero)")
        self.resize(460, 260)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Detecta estrellas reales y las empareja por FORMA (asterismos de 4 estrellas, invariante a "
            "rotación/escala) contra la caché local de catálogos -- sin necesitar ninguna posición ni nombre "
            "de objeto. Solo funciona si ya hay un catálogo descargado que cubra esta zona del cielo."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self._cache = CatalogCache("gaia")
        self.cache_status_label = QLabel(self._cache.describe())
        self.cache_status_label.setObjectName("Muted")
        self.cache_status_label.setWordWrap(True)
        layout.addWidget(self.cache_status_label)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.solve_button = self.button_box.addButton("Resolver en ciego", QDialogButtonBox.ButtonRole.ActionRole)
        self.solve_button.clicked.connect(self._on_solve)
        self.accept_button = self.button_box.addButton("Aceptar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.accept_button.setEnabled(False)
        self.accept_button.clicked.connect(self._on_accept)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_solve(self) -> None:
        self.solve_button.setEnabled(False)
        self.accept_button.setEnabled(False)
        self.status_label.setText("Resolviendo en ciego -- detectando estrellas y buscando asterismos coincidentes...")

        data, header = self._data, self._header

        def run():
            catalog_rows = self._cache.all_rows()
            return solve_plate_blind(data, header, catalog_rows=catalog_rows)

        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_solved)
        self._worker.failed.connect(self._on_failed)
        self._worker.start()

    def _on_solved(self, result) -> None:
        self.solve_button.setEnabled(True)
        if not result.success:
            self.status_label.setText(
                f"PLATE SOLVING CIEGO FALLIDO: {result.reason}\n\n"
                f"Qué puedes hacer: descarga primero un catálogo que cubra esta zona del cielo "
                f"(Catálogos -> Gestionar caché local... -> Descargar campo actual...), o usa "
                f"\"Resolver placa automáticamente...\" si conoces una posición aproximada, o "
                f"\"Ajustar WCS (clic + coordenadas)...\" como alternativa manual."
            )
            return

        self.status_label.setText(
            f"WCS RESUELTO EN CIEGO Y VALIDADO -- {result.reason}\n"
            f"Proveedor: {result.provider}\n"
            f"{result.n_detected_stars} estrella(s) detectada(s), {result.n_catalog_stars} en el catálogo local, "
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
        self.status_label.setText(f"PLATE SOLVING CIEGO FALLIDO: error interno inesperado -- {message}")

    def _on_accept(self) -> None:
        if self._result_solution is None:
            return
        self.accept()

    def result_solution(self):
        return self._result_solution

    def result_table(self) -> Table | None:
        return self._result_table
