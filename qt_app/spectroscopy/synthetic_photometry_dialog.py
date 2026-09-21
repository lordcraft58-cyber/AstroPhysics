"""Magnitud fotométrica sintética desde un espectro (§50) -- diálogo
dedicado (menú Espectroscopía) sobre `astrophysics_suite.spectroscopy.
synthetic_photometry`.

Exige una curva de transmisión de filtro REAL cargada de un archivo
(formato SVO Filter Profile Service) -- ninguna se inventa aquí. Exige
también que la ventana activa ya tenga una calibración en longitud de
onda ajustada: sin ella no hay eje físico contra el que integrar el
filtro. El resultado es una magnitud AB real (definición exacta) --
nunca se etiqueta como "magnitud" el resultado de una normalización o de
cuentas ADU sin calibrar (§37/§41): el propio diálogo lo recuerda en el
mensaje de resultado.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.synthetic_photometry import (
    JOHNSON_COUSINS_FILTERS,
    SDSS_FILTERS,
    FilterCurve,
    ab_magnitude,
    load_filter_curve,
)
from astrophysics_suite.tables.table import Table

_FILTER_REFERENCE_CHOICES: dict[str, object] = {
    f"{info.system} {info.band} (~{info.approximate_central_wavelength_angstrom:.0f} Å)": info
    for info in (*JOHNSON_COUSINS_FILTERS, *SDSS_FILTERS)
}


def _central_row_spectrum(view) -> tuple[np.ndarray, np.ndarray]:
    """Misma convención que `radial_velocity_dialog`/`wavelength_fit_
    dialog`: la fila central de la imagen como espectro 1D."""
    row_index = view.data.shape[0] // 2
    flux = view.data[row_index, :].astype(np.float64)
    pixel = np.arange(flux.size, dtype=np.float64)
    wavelength = view.fitted_wavelength_solution.pixel_to_wavelength(pixel)
    return np.asarray(wavelength, dtype=np.float64), flux


class SyntheticPhotometryDialog(QDialog):
    def __init__(self, view, parent=None):
        super().__init__(parent)
        self._view = view
        self._wavelength, self._flux = _central_row_spectrum(view)
        self._filter_curve: FilterCurve | None = None
        self._last_magnitude: float | None = None
        self.setWindowTitle("Magnitud fotométrica sintética")
        self.resize(520, 320)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Magnitud AB real (Oke & Gunn 1983) integrando el espectro de la fila central contra una curva de "
            "transmisión de filtro REAL cargada de un archivo (formato SVO Filter Profile Service). Este diálogo "
            "nunca inventa una curva de filtro ni un punto cero. AVISO: solo da una magnitud físicamente real si el "
            "flujo de esta ventana ya está calibrado en unidades físicas (erg/s/cm²/Å) -- sobre ADU sin calibrar, "
            "o un espectro solo normalizado a continuo=1, el número no es una magnitud real (§37/§41)."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.filter_reference_combo = QComboBox()
        self.filter_reference_combo.addItem("(sin especificar)")
        self.filter_reference_combo.addItems(list(_FILTER_REFERENCE_CHOICES))
        form.addRow("Filtro de referencia (informativo)", self.filter_reference_combo)
        layout.addLayout(form)

        self.load_filter_button = QPushButton("Cargar curva de filtro (SVO, .dat)...")
        self.load_filter_button.clicked.connect(self._on_load_filter)
        layout.addWidget(self.load_filter_button)

        self.filter_label = QLabel("Ninguna curva de filtro cargada todavía.")
        self.filter_label.setWordWrap(True)
        layout.addWidget(self.filter_label)

        self.compute_button = QPushButton("Calcular magnitud AB")
        self.compute_button.clicked.connect(self._on_compute)
        layout.addWidget(self.compute_button)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    def _on_load_filter(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Cargar curva de transmisión de filtro", "", "Curva de filtro (*.dat *.txt *.csv);;Todos los archivos (*.*)"
        )
        if not path:
            return
        reference_name = self.filter_reference_combo.currentText()
        name = reference_name if reference_name != "(sin especificar)" else path
        try:
            self._filter_curve = load_filter_curve(path, name=name)
        except (ValueError, OSError) as exc:
            self.filter_label.setText(f"No se pudo cargar «{path}»: {exc}")
            self._filter_curve = None
            return
        lo, hi = self._filter_curve.wavelength_angstrom[0], self._filter_curve.wavelength_angstrom[-1]
        self.filter_label.setText(
            f"Filtro «{self._filter_curve.name}» cargado: {lo:.1f}-{hi:.1f} Å "
            f"({self._filter_curve.wavelength_angstrom.size} punto(s) reales de la curva)."
        )

    def _on_compute(self) -> None:
        if self._filter_curve is None:
            self.result_label.setText("Carga primero una curva de transmisión de filtro real.")
            return
        magnitude = ab_magnitude(self._wavelength, self._flux, self._filter_curve)
        if magnitude is None:
            self.result_label.setText(
                f"No se pudo calcular: el espectro de {self._view.title} no cubre por completo el rango del filtro "
                f"«{self._filter_curve.name}», o el flujo efectivo no es positivo."
            )
            self._last_magnitude = None
            return
        self._last_magnitude = magnitude
        self.result_label.setText(
            f"m_AB = {magnitude:.3f} (filtro «{self._filter_curve.name}») -- válida solo si el flujo de esta "
            "ventana ya está calibrado físicamente, no como mera normalización."
        )

    def result_table(self) -> Table | None:
        if self._last_magnitude is None or self._filter_curve is None:
            return None
        return Table(
            columns=("filter", "ab_magnitude"), units=("", "mag"),
            rows=((self._filter_curve.name, self._last_magnitude),),
        )
