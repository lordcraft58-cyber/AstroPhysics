"""Registro entre imágenes por WCS compartido -- equivalente propio de la
parte de `geomap`/`geotran` de IRAF cuando ambas imágenes ya tienen una
solución astrométrica, sobre
`astrophysics_suite.astrometry.registration.reproject_to_reference` sin
ningún cambio. Necesita elegir una segunda ventana MDI, igual que la
aritmética entre imágenes -- mismo patrón de diálogo dedicado (menú
Astrometría, no el árbol de procesos genérico).
"""
from __future__ import annotations

from dataclasses import dataclass

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QDialog, QDialogButtonBox, QFormLayout, QLabel, QVBoxLayout

from astrophysics_suite.astrometry.provenance import ENGINE_REGISTRATION, RegistrationRecord
from astrophysics_suite.astrometry.registration import reproject_to_reference
from astrophysics_suite.astrometry.wcs_fit import WCSSolution, wcs_solution_from_astropy
from qt_app.workers import CallableWorker


@dataclass(frozen=True)
class RegistrationOutcome:
    data: object
    title: str
    record: RegistrationRecord
    """Trae el WCS de la referencia, real para la rejilla de `data` --
    lo que hace falta para poder ofrecer guardar el resultado con
    procedencia real (ver `main_window._offer_to_save_registration_fits`)."""


def _resolve_wcs_solution(view) -> WCSSolution | None:
    """Prioriza un WCS recién ajustado a mano sobre el cargado del FITS
    -- si el usuario acaba de ajustar uno en esta sesión (ver "Ajustar
    WCS..."), es más probable que refleje lo que quiere usar ahora que el
    de la cabecera original."""
    if view.fitted_wcs_solution is not None:
        return view.fitted_wcs_solution
    if view.wcs is not None:
        return wcs_solution_from_astropy(view.wcs)
    return None


class RegistrationDialog(QDialog):
    computed = Signal(object)
    """Emite un `RegistrationOutcome` real -- no solo (datos, título) --
    para que el llamador pueda ofrecer guardarlo con procedencia real."""

    def __init__(self, views: dict[str, object], active_title: str, parent=None):
        """`views`: título de ventana -> `ImageView` (se necesita el
        objeto completo, no solo los píxeles, para leer su WCS)."""
        super().__init__(parent)
        self._views = views
        self.setWindowTitle("Registrar por WCS compartido")
        self.resize(440, 200)
        self._worker: CallableWorker | None = None

        layout = QVBoxLayout(self)
        form = QFormLayout()

        titles = list(views.keys())
        self.reference_combo = QComboBox()
        self.reference_combo.addItems(titles)
        if active_title in views:
            self.reference_combo.setCurrentText(active_title)
        form.addRow("Imagen de referencia", self.reference_combo)

        self.target_combo = QComboBox()
        self.target_combo.addItems(titles)
        if len(titles) > 1:
            self.target_combo.setCurrentIndex(1 if titles[0] == active_title else 0)
        form.addRow("Imagen a reproyectar", self.target_combo)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.apply_button = self.button_box.addButton("Reproyectar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.apply_button.clicked.connect(self._on_apply)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_apply(self) -> None:
        reference_title = self.reference_combo.currentText()
        target_title = self.target_combo.currentText()
        if reference_title == target_title:
            self.status_label.setText("Elige dos ventanas distintas.")
            return

        reference_view = self._views[reference_title]
        target_view = self._views[target_title]
        reference_solution = _resolve_wcs_solution(reference_view)
        target_solution = _resolve_wcs_solution(target_view)
        if reference_solution is None or target_solution is None:
            missing = reference_title if reference_solution is None else target_title
            self.status_label.setText(f"«{missing}» no tiene WCS (ni cargado ni ajustado a mano) -- usa «Ajustar WCS...» primero.")
            return

        output_shape = reference_view.data.shape
        target_data = target_view.data
        title = f"{target_title} -> WCS de {reference_title}"

        def run() -> RegistrationOutcome:
            resampled = reproject_to_reference(target_data, target_solution, reference_solution, output_shape=output_shape)
            record = RegistrationRecord(
                engine=ENGINE_REGISTRATION, reference_title=reference_title, target_title=target_title,
                reference_wcs=reference_solution,
            )
            return RegistrationOutcome(data=resampled, title=title, record=record)

        self.apply_button.setEnabled(False)
        self.status_label.setText("Reproyectando...")
        self._worker = CallableWorker(run, self)
        self._worker.finished_ok.connect(self._on_success)
        self._worker.failed.connect(self._on_failure)
        self._worker.start()

    def _on_success(self, outcome: RegistrationOutcome) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText("")
        self.computed.emit(outcome)
        self.accept()

    def _on_failure(self, message: str) -> None:
        self.apply_button.setEnabled(True)
        self.status_label.setText(f"Error: {message}")
