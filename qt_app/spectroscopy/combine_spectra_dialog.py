"""Combinación de espectros 1D -- diálogo dedicado (menú Espectroscopía)
sobre `astrophysics_suite.spectroscopy.combine.combine_spectra`, mismo
patrón que "Registrar por WCS compartido...": necesita elegir varias
ventanas MDI (dos o más), no encaja en el árbol de procesos genérico que
opera sobre la imagen activa.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.combine import combine_spectra
from astrophysics_suite.tables.table import Table


def _central_row_spectrum(view) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Misma convención que spectroscopy.continuum/spectroscopy.line: la
    fila central de la imagen tratada como espectro 1D. Usa la
    calibración en longitud de onda de la ventana si ya se ajustó una
    ("Calibrar longitud de onda..."), o el eje de píxeles si no."""
    row_index = view.data.shape[0] // 2
    flux = view.data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    if view.fitted_wavelength_solution is not None:
        wavelength = view.fitted_wavelength_solution.pixel_to_wavelength(pixel)
    else:
        wavelength = pixel
    flux_uncertainty = np.sqrt(np.clip(view.data, 1.0, None))[row_index, :].astype(np.float64)
    return wavelength, flux, flux_uncertainty


class CombineSpectraDialog(QDialog):
    combined = Signal(object, object)
    """Emite `(CombinedSpectrum, Table)` al combinar con éxito."""

    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self.setWindowTitle("Combinar espectros")
        self.resize(440, 420)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Marca dos o más ventanas -- cada una se trata como un espectro 1D (fila central, "
            "misma convención que 'Ajuste de continuo'/'Medición de línea'), usando la calibración "
            "en longitud de onda de cada ventana si ya se ajustó una, o el eje de píxeles si no. "
            "No se pueden mezclar ventanas calibradas con no calibradas -- calibra todas o ninguna."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        self.list_widget = QListWidget()
        for title in views:
            item = QListWidgetItem(title)
            item.setFlags(item.flags() | Qt.ItemFlag.ItemIsUserCheckable)
            item.setCheckState(Qt.CheckState.Unchecked)
            self.list_widget.addItem(item)
        layout.addWidget(self.list_widget)

        form = QFormLayout()
        self.method_combo = QComboBox()
        self.method_combo.addItems(["median", "mean"])
        form.addRow("Método", self.method_combo)

        self.sigma_clip_check = QCheckBox("Rechazar atípicos (sigma-clip)")
        self.sigma_clip_check.setChecked(True)
        form.addRow(self.sigma_clip_check)

        self.sigma_clip_spin = QDoubleSpinBox()
        self.sigma_clip_spin.setRange(0.5, 10.0)
        self.sigma_clip_spin.setValue(3.0)
        self.sigma_clip_spin.setDecimals(1)
        form.addRow("Umbral σ de rechazo", self.sigma_clip_spin)
        layout.addLayout(form)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.combine_button = self.button_box.addButton("Combinar", QDialogButtonBox.ButtonRole.AcceptRole)
        self.combine_button.clicked.connect(self._on_combine)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _checked_titles(self) -> list[str]:
        titles = []
        for i in range(self.list_widget.count()):
            item = self.list_widget.item(i)
            if item.checkState() == Qt.CheckState.Checked:
                titles.append(item.text())
        return titles

    def _on_combine(self) -> None:
        titles = self._checked_titles()
        if len(titles) < 2:
            self.status_label.setText("Marca al menos dos ventanas para combinar.")
            return

        views = [self._views[title] for title in titles]
        has_solution = [v.fitted_wavelength_solution is not None for v in views]
        if any(has_solution) and not all(has_solution):
            uncalibrated = [t for t, calibrated in zip(titles, has_solution) if not calibrated]
            self.status_label.setText(
                f"Mezcla de ventanas calibradas y sin calibrar en longitud de onda -- calibra también "
                f"{', '.join(uncalibrated)} (o ninguna) antes de combinar."
            )
            return

        wavelengths, fluxes, uncertainties = [], [], []
        for v in views:
            w, f, u = _central_row_spectrum(v)
            wavelengths.append(w)
            fluxes.append(f)
            uncertainties.append(u)

        method = self.method_combo.currentText()
        sigma_clip = self.sigma_clip_spin.value() if self.sigma_clip_check.isChecked() else None

        try:
            result = combine_spectra(wavelengths, fluxes, uncertainties, method=method, sigma_clip=sigma_clip)
        except ValueError as exc:
            self.status_label.setText(f"Error: {exc}")
            return

        n_valid = int(np.count_nonzero(~np.isnan(result.flux)))
        self.status_label.setText(f"Combinados {len(titles)} espectro(s) ({method}); {n_valid}/{result.wavelength.size} puntos con dato real.")

        wavelength_unit = "Å" if all(has_solution) else "px"
        table = Table(
            columns=("wavelength", "flux", "flux_uncertainty", "n_combined", "n_rejected"),
            units=(wavelength_unit, "ADU", "ADU", "", ""),
            rows=tuple(zip(result.wavelength.tolist(), result.flux.tolist(), result.flux_uncertainty.tolist(), result.n_combined.tolist(), result.n_rejected.tolist())),
        )
        self.combined.emit(result, table)
        self.accept()
