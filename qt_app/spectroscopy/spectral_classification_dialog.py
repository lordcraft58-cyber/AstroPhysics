"""Clasificación espectral navegando el atlas real (§25/§26, estilo
Vireo): tres paneles apilados (estándar / observado / resultado) que se
actualizan al momento con cada clic en la lista de las 161 estrellas
reales del atlas Jacoby-Hunter-Christian (1984) -- la misma disposición
que ya usa el usuario en Vireo para esta tarea.

Reutiliza `template_comparison.compare_to_template` (nunca duplica la
comparación) y `jacoby_atlas` (informe 103) para el atlas real. Nunca
clasifica nada por sí solo: el usuario navega, ve el resultado real bajo
cada estándar (resta o cociente, a elegir), y decide -- mismo principio
que ya documenta `template_comparison.py`.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QFormLayout,
    QLabel,
    QListWidget,
    QSplitter,
    QVBoxLayout,
    QWidget,
)

from astrophysics_suite.spectroscopy.jacoby_atlas import (
    JacobyAtlasEntry,
    bundled_atlas_paths,
    load_jacoby_atlas_index,
    load_jacoby_atlas_spectrum,
)
from astrophysics_suite.spectroscopy.line_catalog import NAMED_OBJECT_LINE_CATALOGS
from astrophysics_suite.spectroscopy.template_comparison import compare_to_template
from qt_app.spectroscopy.spectrum_plot_data import SpectrumMarker, SpectrumPlotData, SpectrumSeries, series_color
from qt_app.spectroscopy.spectrum_view import SpectrumView

_LOW_OVERLAP_THRESHOLD = 0.5
_MARKER_HALF_WIDTH_ANGSTROM = 1.0
_EMPTY_PLOT_DATA = SpectrumPlotData(series=(), x_label="Longitud de onda (Å)", y_label="Flujo normalizado")


class SpectralClassificationDialog(QDialog):
    def __init__(self, views: dict[str, object], parent=None):
        super().__init__(parent)
        self._views = views
        self.setWindowTitle("Clasificación espectral (atlas Jacoby-Hunter-Christian)")
        self.resize(920, 800)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Navega por las 161 estrellas reales del atlas -- cada clic en la lista actualiza los tres paneles al "
            "momento, sin pulsar nada más. NUNCA clasifica por sí sola: tú decides qué estándar se parece más."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        controls = QFormLayout()
        self.observed_combo = QComboBox()
        self.observed_combo.addItems(list(views))
        self.observed_combo.currentIndexChanged.connect(self._update)
        controls.addRow("Ventana observada (ya calibrada)", self.observed_combo)
        self.operation_combo = QComboBox()
        self.operation_combo.addItems(["Resta (observado - estándar)", "Cociente (observado / estándar)"])
        self.operation_combo.currentIndexChanged.connect(self._update)
        controls.addRow("Operación", self.operation_combo)
        self.normalize_combo = QComboBox()
        self.normalize_combo.addItems(["median", "none"])
        self.normalize_combo.setToolTip(
            "median: reescala cada espectro por su propia mediana real sobre el solape (compara la FORMA). "
            "none: valores tal cual (los dos ya en las mismas unidades)."
        )
        self.normalize_combo.currentIndexChanged.connect(self._update)
        controls.addRow("Normalización", self.normalize_combo)
        self.lines_checkbox = QCheckBox("Marcar líneas químicas conocidas (Balmer/Ca II/Na D/nebulares)")
        self.lines_checkbox.setChecked(True)
        self.lines_checkbox.toggled.connect(self._update)
        controls.addRow(self.lines_checkbox)
        layout.addLayout(controls)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.standards_list = QListWidget()
        self.standards_list.setMinimumWidth(230)
        self.standards_list.currentRowChanged.connect(self._update)
        splitter.addWidget(self.standards_list)

        plots_container = QWidget()
        plots_layout = QVBoxLayout(plots_container)
        plots_layout.setContentsMargins(0, 0, 0, 0)
        self.standard_view = SpectrumView(_EMPTY_PLOT_DATA, "Estándar", plots_container)
        self.observed_view = SpectrumView(_EMPTY_PLOT_DATA, "Observado", plots_container)
        self.result_view = SpectrumView(_EMPTY_PLOT_DATA, "Resultado", plots_container)
        for view in (self.standard_view, self.observed_view, self.result_view):
            view.setMinimumHeight(160)
            plots_layout.addWidget(view)
        splitter.addWidget(plots_container)
        splitter.setStretchFactor(1, 1)
        layout.addWidget(splitter, stretch=1)

        self.status_label = QLabel("Elige una ventana observada ya calibrada y un estándar de la lista.")
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        self.button_box.accepted.connect(self.accept)
        layout.addWidget(self.button_box)

        self._atlas_entries: tuple[JacobyAtlasEntry, ...] = ()
        self._atlas_spectra_dir = None
        try:
            inx_path, self._atlas_spectra_dir = bundled_atlas_paths()
            self._atlas_entries = load_jacoby_atlas_index(inx_path)
        except (ValueError, OSError) as exc:
            self.status_label.setText(f"Atlas no disponible: {exc}")
            self.standards_list.setEnabled(False)
        else:
            self.standards_list.addItems([entry.label for entry in self._atlas_entries])

    # ------------------------------------------------------------ actualización en vivo
    def _update(self, *_args) -> None:
        row = self.standards_list.currentRow()
        if row < 0 or row >= len(self._atlas_entries) or self._atlas_spectra_dir is None:
            return
        view = self._views.get(self.observed_combo.currentText())
        if view is None:
            self.status_label.setText("Elige una ventana observada real.")
            return
        if view.fitted_wavelength_solution is None:
            self.status_label.setText(
                f"{view.title} no tiene una calibración en longitud de onda ajustada todavía -- usa antes "
                "\"Autoprocesar espectro (§34)\" o \"Calibrar longitud de onda...\"."
            )
            return

        entry = self._atlas_entries[row]
        try:
            template_wavelength, template_flux = load_jacoby_atlas_spectrum(entry, self._atlas_spectra_dir)
        except ValueError as exc:
            self.status_label.setText(f"No se pudo cargar «{entry.label}»: {exc}")
            return
        if view.wavelength_calibration_spectrum is None:
            self.status_label.setText(
                f"{view.title} no tiene guardado el espectro real sobre el que se calibró -- "
                "vuelve a calibrar (p. ej. \"Autoprocesar espectro (§34)\")."
            )
            return

        # El espectro REAL ya extraído (§13/§34) -- nunca la fila central
        # del fotograma 2D crudo, sin extracción ni resta de cielo: eso
        # comparaba forma de continuo de una sola fila, no el espectro
        # real (hallazgo real del usuario).
        observed_flux = np.asarray(view.wavelength_calibration_spectrum, dtype=np.float64)
        pixel = np.arange(observed_flux.size, dtype=np.float64)
        observed_wavelength = np.asarray(view.fitted_wavelength_solution.pixel_to_wavelength(pixel), dtype=np.float64)

        operation = "divide" if self.operation_combo.currentIndex() == 1 else "subtract"
        try:
            result = compare_to_template(
                observed_wavelength, observed_flux, template_wavelength, template_flux,
                normalize=self.normalize_combo.currentText(), operation=operation,
            )
        except ValueError as exc:
            self.status_label.setText(f"No se pudo comparar: {exc}")
            return

        overlap_note = "" if result.overlap_fraction >= _LOW_OVERLAP_THRESHOLD else " -- AVISO: solape bajo, la comparación es poco significativa."
        self.status_label.setText(f"{entry.label} -- solape real: {result.overlap_fraction:.1%} del rango observado.{overlap_note}")

        wl_min, wl_max = float(np.nanmin(result.wavelength)), float(np.nanmax(result.wavelength))
        markers = self._chemical_markers(wl_min, wl_max) if self.lines_checkbox.isChecked() else ()
        result_label = "Cociente (observado / estándar)" if operation == "divide" else "Diferencia (observado - estándar)"

        self.standard_view.set_plot_data(SpectrumPlotData(
            series=(SpectrumSeries(label=f"Estándar: {entry.label}", x=result.wavelength, y=result.template_flux, color=series_color(1)),),
            x_label="Longitud de onda (Å)", y_label="Flujo normalizado", markers=markers,
        ))
        self.observed_view.set_plot_data(SpectrumPlotData(
            series=(SpectrumSeries(label=f"Observado: {view.title}", x=result.wavelength, y=result.observed_flux, color=series_color(0)),),
            x_label="Longitud de onda (Å)", y_label="Flujo normalizado", markers=markers,
        ))
        self.result_view.set_plot_data(SpectrumPlotData(
            series=(SpectrumSeries(label=result_label, x=result.wavelength, y=result.residual, color=series_color(2)),),
            x_label="Longitud de onda (Å)", y_label=result_label, markers=markers,
        ))

    def _chemical_markers(self, wl_min: float, wl_max: float) -> tuple[SpectrumMarker, ...]:
        seen: set[float] = set()
        markers: list[SpectrumMarker] = []
        for catalog in NAMED_OBJECT_LINE_CATALOGS.values():
            for line in catalog:
                if line.wavelength_air_angstrom in seen or not (wl_min <= line.wavelength_air_angstrom <= wl_max):
                    continue
                seen.add(line.wavelength_air_angstrom)
                markers.append(SpectrumMarker(
                    x_start=line.wavelength_air_angstrom - _MARKER_HALF_WIDTH_ANGSTROM,
                    x_end=line.wavelength_air_angstrom + _MARKER_HALF_WIDTH_ANGSTROM,
                    label=line.label, color="#8888ff",
                ))
        return tuple(sorted(markers, key=lambda marker: marker.x_start))
