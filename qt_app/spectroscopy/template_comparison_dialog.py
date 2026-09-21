"""Comparación con plantilla de referencia (§25) -- diálogo dedicado
(menú Espectroscopía) sobre `astrophysics_suite.spectroscopy.template_
comparison`.

La ventana observada (ya calibrada en longitud de onda, misma
convención de fila central que el resto de diálogos de espectroscopía)
se compara contra una plantilla real elegida por el usuario -- cualquier
otra observación propia, una estrella estándar, o un espectro de
referencia guardado por otro programa -- ya sea un FITS 1D con WCS de
longitud de onda real, un archivo de texto de dos columnas (longitud de
onda, flujo, el formato en que suelen venir las bibliotecas espectrales
externas), o un estándar real del atlas Jacoby-Hunter-Christian (1984)
ya incluido (`spectroscopy.jacoby_atlas`, 161 estrellas reales O5V-M7,
aportado por el propio usuario). Nunca clasifica ni sugiere un tipo
espectral automáticamente: muestra observado, plantilla y residuo real,
y avisa si el solape real entre los dos es bajo -- la decisión de qué
significa el residuo (y de con qué estándar comparar) es siempre del
usuario, igual que si estuviera repitiendo a mano la comparación contra
varios estándares que ya hace en otro programa de clasificación.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.jacoby_atlas import (
    JacobyAtlasEntry,
    bundled_atlas_paths,
    load_jacoby_atlas_index,
    load_jacoby_atlas_spectrum,
)
from astrophysics_suite.spectroscopy.spectrum1d_io import import_ascii_spectrum, load_spectrum1d_fits
from astrophysics_suite.spectroscopy.template_comparison import TemplateComparisonResult, compare_to_template
from astrophysics_suite.tables.table import Table
from qt_app.spectroscopy.spectrum_plot_data import SpectrumPlotData, SpectrumSeries, series_color

_LOW_OVERLAP_THRESHOLD = 0.5


class TemplateComparisonDialog(QDialog):
    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self._template_path: str | None = None
        self._template_wavelength: np.ndarray | None = None
        self._template_flux: np.ndarray | None = None
        self._last_result: TemplateComparisonResult | None = None
        self.setWindowTitle("Comparación con plantilla de referencia")
        self.resize(560, 360)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Compara el espectro observado con OTRO espectro 1D real que elijas como plantilla (otra observación "
            "propia, una estrella estándar, cualquier FITS 1D ya calibrado en longitud de onda) -- muestra los dos "
            "y el residuo real punto a punto (§25). NUNCA clasifica ni sugiere un tipo espectral automáticamente: "
            "la decisión es siempre tuya."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        form = QFormLayout()
        self.observed_combo = QComboBox()
        self.observed_combo.addItems(list(views))
        form.addRow("Ventana observada (ya calibrada)", self.observed_combo)
        self.normalize_combo = QComboBox()
        self.normalize_combo.addItems(["median", "none"])
        self.normalize_combo.setToolTip(
            "median: reescala cada espectro por su propia mediana real sobre el solape (compara la FORMA aunque "
            "los niveles de flujo absolutos difieran). none: valores tal cual (los dos ya en las mismas unidades)."
        )
        form.addRow("Normalización", self.normalize_combo)
        layout.addLayout(form)

        template_row = QHBoxLayout()
        self.template_button = QPushButton("Elegir plantilla (FITS 1D)...")
        self.template_button.clicked.connect(self._on_choose_template)
        template_row.addWidget(self.template_button)
        self.template_ascii_button = QPushButton("Importar plantilla desde texto (λ, flujo)...")
        self.template_ascii_button.clicked.connect(self._on_import_ascii_template)
        template_row.addWidget(self.template_ascii_button)
        layout.addLayout(template_row)

        atlas_row = QHBoxLayout()
        self.atlas_combo = QComboBox()
        self.atlas_combo.setToolTip(
            "161 estrellas reales O5V-M7 del atlas Jacoby, Hunter & Christian (1984, ApJS 56, 257) -- "
            "incluido tal cual, aportado por el usuario."
        )
        atlas_row.addWidget(self.atlas_combo, stretch=1)
        self.atlas_button = QPushButton("Usar este estándar del atlas")
        self.atlas_button.clicked.connect(self._on_use_atlas_standard)
        atlas_row.addWidget(self.atlas_button)
        layout.addLayout(atlas_row)

        self._atlas_entries: tuple[JacobyAtlasEntry, ...] = ()
        try:
            atlas_inx_path, self._atlas_spectra_dir = bundled_atlas_paths()
            self._atlas_entries = load_jacoby_atlas_index(atlas_inx_path)
        except (ValueError, OSError) as exc:
            self._atlas_spectra_dir = None
            self.atlas_combo.addItem(f"Atlas no disponible: {exc}")
            self.atlas_combo.setEnabled(False)
            self.atlas_button.setEnabled(False)
        else:
            self.atlas_combo.addItems([entry.label for entry in self._atlas_entries])

        self.template_label = QLabel("Ninguna plantilla elegida todavía.")
        self.template_label.setWordWrap(True)
        layout.addWidget(self.template_label)

        self.compare_button = QPushButton("Comparar")
        self.compare_button.clicked.connect(self._on_compare)
        layout.addWidget(self.compare_button)

        self.result_label = QLabel("")
        self.result_label.setWordWrap(True)
        layout.addWidget(self.result_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

    def _on_choose_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "Elegir plantilla (FITS 1D)", "", "FITS (*.fits *.fit *.fts)")
        if not path:
            return
        try:
            wavelength, flux, _header = load_spectrum1d_fits(path)
        except (ValueError, OSError) as exc:
            self.template_label.setText(f"No se pudo cargar «{Path(path).name}»: {exc}")
            return
        self._template_path = path
        self._template_wavelength = wavelength
        self._template_flux = flux
        self.template_label.setText(
            f"Plantilla: {Path(path).name} ({wavelength.size} punto(s), "
            f"{wavelength.min():.1f}-{wavelength.max():.1f} Å)."
        )

    def _on_import_ascii_template(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Importar plantilla desde texto (longitud de onda, flujo)", "", "Texto (*.txt *.dat *.ssp *.asc);;Todos los archivos (*.*)"
        )
        if not path:
            return
        try:
            wavelength, flux, header_line = import_ascii_spectrum(path)
        except (ValueError, OSError) as exc:
            self.template_label.setText(f"No se pudo importar «{Path(path).name}»: {exc}")
            return
        self._template_path = path
        self._template_wavelength = wavelength
        self._template_flux = flux
        origin_note = f" -- cabecera de origen: {header_line}" if header_line else ""
        self.template_label.setText(
            f"Plantilla (importada de texto): {Path(path).name} ({wavelength.size} punto(s), "
            f"{wavelength.min():.1f}-{wavelength.max():.1f} Å){origin_note}."
        )

    def _on_use_atlas_standard(self) -> None:
        if not self._atlas_entries or self._atlas_spectra_dir is None:
            return
        index = self.atlas_combo.currentIndex()
        if index < 0 or index >= len(self._atlas_entries):
            return
        entry = self._atlas_entries[index]
        try:
            wavelength, flux = load_jacoby_atlas_spectrum(entry, self._atlas_spectra_dir)
        except ValueError as exc:
            self.template_label.setText(f"No se pudo cargar el estándar «{entry.label}»: {exc}")
            return
        self._template_path = f"jacoby_atlas:{entry.index}"
        self._template_wavelength = wavelength
        self._template_flux = flux
        self.template_label.setText(
            f"Plantilla (atlas Jacoby-Hunter-Christian 1984): {entry.label} ({wavelength.size} punto(s), "
            f"{wavelength.min():.1f}-{wavelength.max():.1f} Å)."
        )

    def _on_compare(self) -> None:
        view = self._views.get(self.observed_combo.currentText())
        if view is None:
            self.result_label.setText("Elige una ventana real.")
            return
        if view.fitted_wavelength_solution is None:
            self.result_label.setText(
                f"{view.title} no tiene una calibración en longitud de onda ajustada todavía -- "
                "usa antes \"Calibrar longitud de onda...\"."
            )
            return
        if self._template_wavelength is None or self._template_flux is None:
            self.result_label.setText("Elige primero una plantilla real (FITS 1D).")
            return
        if view.wavelength_calibration_spectrum is None:
            self.result_label.setText(
                f"{view.title} no tiene guardado el espectro real sobre el que se calibró -- "
                "vuelve a calibrar (p. ej. \"Autoprocesar espectro (§34)\")."
            )
            return

        # El espectro REAL ya extraído (§13/§34, óptimo/suma/media según se
        # haya usado) -- nunca la fila central del fotograma 2D crudo, sin
        # extracción ni resta de cielo: eso comparaba forma de continuo de
        # una sola fila, no el espectro real (hallazgo real del usuario).
        flux = np.asarray(view.wavelength_calibration_spectrum, dtype=np.float64)
        pixel = np.arange(flux.size, dtype=np.float64)
        wavelength = np.asarray(view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)

        try:
            result = compare_to_template(
                wavelength, flux, self._template_wavelength, self._template_flux,
                normalize=self.normalize_combo.currentText(),
            )
        except ValueError as exc:
            self.result_label.setText(f"No se pudo comparar: {exc}")
            self._last_result = None
            return

        self._last_result = result
        overlap_note = "" if result.overlap_fraction >= _LOW_OVERLAP_THRESHOLD else " -- AVISO: solape bajo, la comparación es poco significativa."
        self.result_label.setText(f"Solape real con la plantilla: {result.overlap_fraction:.1%} del rango observado.{overlap_note}")

        y_label = "Flujo normalizado (mediana=1)" if self.normalize_combo.currentText() == "median" else "Flujo (unidades originales)"
        plot_data = SpectrumPlotData(
            series=(
                SpectrumSeries(label=f"Observado ({view.title})", x=result.wavelength, y=result.observed_flux, color=series_color(0)),
                SpectrumSeries(
                    label=f"Plantilla ({Path(self._template_path).name})", x=result.wavelength, y=result.template_flux,
                    color=series_color(1), style="dashed",
                ),
                SpectrumSeries(label="Residuo (observado - plantilla)", x=result.wavelength, y=result.residual, color=series_color(2)),
            ),
            x_label="Longitud de onda (Å)", y_label=y_label, x_unit="Å",
        )
        main_window = self.parent()
        if main_window is None or not hasattr(main_window, "add_spectrum_window"):
            self.result_label.setText(self.result_label.text() + " (no se pudo abrir la ventana de comparación)")
            return
        main_window.add_spectrum_window(plot_data, f"Comparación con plantilla -- {view.title}")

    def result_table(self) -> Table | None:
        if self._last_result is None:
            return None
        result = self._last_result
        return Table(
            columns=("overlap_fraction", "observed_scale", "template_scale"),
            units=("", "", ""),
            rows=((result.overlap_fraction, result.observed_scale, result.template_scale),),
        )
