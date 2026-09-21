"""Calibración en longitud de onda desde líneas de arco detectadas
automáticamente -- equivalente propio de `identify` de IRAF, sobre
`astrophysics_suite.spectroscopy.wavelength.find_arc_lines`/
`fit_wavelength_solution` sin ningún cambio. A diferencia del ajuste de
WCS (Fase 13), la localización de las líneas SÍ es automática
(`find_arc_lines` detecta picos reales sobre un fondo local robusto); lo
que el taller no puede adivinar es a qué longitud de onda conocida
corresponde cada línea detectada -- eso lo aporta el usuario, igual que
`identify` interactivo pide asociar cada línea marcada con una entrada de
un catálogo de lámpara (Hg/Ar/Ne...).

Sugerencia automática (§10): si el usuario elige una lámpara conocida y
da una dispersión/origen aproximados (de la óptica del instrumento, o
de una calibración previa), `line_catalog.match_lines_to_catalog`
propone una longitud de onda por línea detectada -- **propone, no
aplica**: el usuario sigue viendo y pudiendo corregir cada celda antes
de pulsar "Ajustar solución", la etapa de confirmación que pide el
encargo explícitamente.

Perfiles de instrumento (§12): además de ajustar una calibración nueva
desde cero, el usuario puede reutilizar una solución ya validada para
esta configuración de instrumento -- tal cual ("Usar perfil tal cual",
`CalibrationSource.REUSED_INSTRUMENTAL`), o recalculando SOLO el
desplazamiento global A0 por correlación cruzada contra el espectro de
lámpara guardado en el perfil ("Recalcular solo el offset A0"), nunca
un reajuste completo sin nueva evidencia de líneas. `services.
spectral_calibration_profiles` avisa explícitamente del riesgo de
deriva mecánica/térmica en ese segundo caso.
"""
from __future__ import annotations

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QGridLayout,
    QHBoxLayout,
    QHeaderView,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
)

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.line_catalog import arc_catalog, match_lines_to_catalog
from astrophysics_suite.spectroscopy.wavelength import ArcLine, fit_wavelength_solution
from astrophysics_suite.tables.table import Table
from services.spectral_calibration_profiles import (
    SpectralCalibrationProfileStore,
    profile_from_record,
    reidentify_profile_offset,
)

_LAMP_OPTIONS = ("(sin especificar)", "Ne", "Ar", "He", "HeNeAr")
_NO_PROFILE = "(ningún perfil)"
_EMPTY_LINE_TABLE = Table(columns=("line", "pixel", "wavelength", "residual"), units=("", "px", "", ""), rows=())
"""Tabla vacía para cuando la solución viene de un perfil reutilizado
(§12): el perfil guarda los coeficientes ya ajustados, no las líneas
individuales que los produjeron -- una tabla "por línea" inventada aquí
sería un dato falso."""


class WavelengthFitDialog(QDialog):
    fitted = Signal(object, object, object)
    """Emite `(WavelengthSolution, Table, WavelengthCalibrationRecord)`
    al ajustar con éxito -- el `record` lleva la lámpara declarada (si
    se dio) y `CalibrationSource.LAMP_REAL`: esta calibración siempre
    parte de líneas que el usuario ha confirmado a mano, nunca de una
    suposición aceptada en silencio."""

    def __init__(
        self,
        lines: list[ArcLine],
        parent=None,
        *,
        spectrum: np.ndarray | None = None,
        profile_store: SpectralCalibrationProfileStore | None = None,
    ):
        super().__init__(parent)
        self._lines = lines
        self._spectrum = spectrum
        """El espectro 1D real (ADU) sobre el que se detectaron `lines`
        -- se guarda junto con cualquier perfil que el usuario decida
        persistir (§12), y es contra lo que se correlaciona un
        perfil ya guardado al recalcular solo su desplazamiento."""
        self.profile_store = profile_store or SpectralCalibrationProfileStore()
        self._last_record: WavelengthCalibrationRecord | None = None
        self.setWindowTitle("Calibrar longitud de onda")
        self.resize(520, 500)

        layout = QVBoxLayout(self)
        hint = QLabel(
            f"Se detectaron {len(lines)} línea(s) de arco automáticamente. Introduce la "
            "longitud de onda conocida (p. ej. de un catálogo de lámpara) para cada una -- "
            "el taller no adivina a qué línea corresponde cada pico sin tu confirmación."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        degree_row = QHBoxLayout()
        degree_row.addWidget(QLabel("Grado del polinomio"))
        self.degree_spin = QSpinBox()
        self.degree_spin.setRange(1, 6)
        self.degree_spin.setValue(min(3, max(1, len(lines) - 1)))
        degree_row.addWidget(self.degree_spin)
        degree_row.addStretch(1)
        layout.addLayout(degree_row)

        suggest_grid = QGridLayout()
        suggest_grid.addWidget(QLabel("Lámpara"), 0, 0)
        self.lamp_combo = QComboBox()
        self.lamp_combo.addItems(_LAMP_OPTIONS)
        suggest_grid.addWidget(self.lamp_combo, 0, 1)
        suggest_grid.addWidget(QLabel("Dispersión aprox. (Å/px)"), 1, 0)
        self.dispersion_spin = QDoubleSpinBox()
        self.dispersion_spin.setRange(0.01, 100.0)
        self.dispersion_spin.setDecimals(3)
        self.dispersion_spin.setValue(1.4)
        suggest_grid.addWidget(self.dispersion_spin, 1, 1)
        suggest_grid.addWidget(QLabel("λ en píxel 0 aprox. (Å)"), 2, 0)
        self.zero_point_spin = QDoubleSpinBox()
        self.zero_point_spin.setRange(0.0, 20000.0)
        self.zero_point_spin.setDecimals(1)
        self.zero_point_spin.setValue(3800.0)
        suggest_grid.addWidget(self.zero_point_spin, 2, 1)
        self.suggest_button = QPushButton("Sugerir automáticamente")
        self.suggest_button.setToolTip(
            "Rellena la columna de longitud de onda con la línea de catálogo más cercana a la "
            "dispersión aproximada dada -- una SUGERENCIA que puedes corregir antes de ajustar, "
            "nunca se aplica sin que la revises."
        )
        self.suggest_button.clicked.connect(self._on_suggest)
        suggest_grid.addWidget(self.suggest_button, 0, 2, 3, 1)
        layout.addLayout(suggest_grid)

        profile_row = QHBoxLayout()
        profile_row.addWidget(QLabel("Perfil de instrumento"))
        self.profile_combo = QComboBox()
        self.profile_combo.addItem(_NO_PROFILE)
        self.profile_combo.addItems(sorted(self.profile_store.load_all().keys()))
        profile_row.addWidget(self.profile_combo, 1)
        self.use_profile_button = QPushButton("Usar tal cual")
        self.use_profile_button.setToolTip(
            "Reutiliza la solución guardada sin recalcular nada (§12) -- se marca como "
            "REUSED_INSTRUMENTAL, nunca como una calibración recién medida en esta imagen."
        )
        self.use_profile_button.clicked.connect(self._on_use_profile)
        profile_row.addWidget(self.use_profile_button)
        self.reidentify_button = QPushButton("Recalcular solo offset (A0)")
        self.reidentify_button.setToolTip(
            "Recalcula SOLO el desplazamiento global por correlación cruzada contra el espectro de "
            "lámpara guardado en el perfil -- nunca la forma completa del polinomio sin nueva evidencia. "
            "Avisa de un posible desplazamiento mecánico/térmico del instrumento."
        )
        self.reidentify_button.clicked.connect(self._on_reidentify_offset)
        profile_row.addWidget(self.reidentify_button)
        layout.addLayout(profile_row)

        self.table = QTableWidget(len(lines), 4, self)
        self.table.setHorizontalHeaderLabels(["Píxel", "Amplitud", "Longitud de onda", "Confianza"])
        for row, line in enumerate(lines):
            pixel_item = QTableWidgetItem(f"{line.pixel:.2f}")
            pixel_item.setFlags(pixel_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            amplitude_item = QTableWidgetItem(f"{line.amplitude:.1f}")
            amplitude_item.setFlags(amplitude_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 0, pixel_item)
            self.table.setItem(row, 1, amplitude_item)
            self.table.setItem(row, 2, QTableWidgetItem(""))
            confidence_item = QTableWidgetItem("")
            confidence_item.setFlags(confidence_item.flags() & ~Qt.ItemFlag.ItemIsEditable)
            self.table.setItem(row, 3, confidence_item)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        layout.addWidget(self.table)

        self.status_label = QLabel("")
        self.status_label.setObjectName("Muted")
        layout.addWidget(self.status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.save_profile_button = self.button_box.addButton(
            "Guardar como perfil...", QDialogButtonBox.ButtonRole.ActionRole
        )
        self.save_profile_button.setToolTip(
            "Guarda la última solución ajustada por líneas (no una reutilizada) como perfil de "
            "instrumento reutilizable en próximas sesiones (§12)."
        )
        self.save_profile_button.clicked.connect(self._on_save_profile)
        self.fit_button = self.button_box.addButton("Ajustar solución", QDialogButtonBox.ButtonRole.AcceptRole)
        self.fit_button.clicked.connect(self._on_fit)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    def _on_suggest(self) -> None:
        lamp_name = self.lamp_combo.currentText()
        if lamp_name == "(sin especificar)":
            self.status_label.setText("Elige una lámpara para poder sugerir correspondencias.")
            return
        catalog = arc_catalog(lamp_name)
        pixels = [line.pixel for line in self._lines]
        matches = match_lines_to_catalog(
            pixels, catalog,
            approx_dispersion_angstrom_per_px=self.dispersion_spin.value(),
            approx_wavelength_at_pixel0=self.zero_point_spin.value(),
            tolerance_angstrom=max(3.0, 3.0 * self.dispersion_spin.value()),
        )
        n_suggested = 0
        for row, match in enumerate(matches):
            if match is None:
                self.table.setItem(row, 3, QTableWidgetItem("sin coincidencia"))
                continue
            self.table.item(row, 2).setText(f"{match.catalog_line.wavelength_air_angstrom:.3f}")
            self.table.item(row, 3).setText(f"{match.confidence:.2f}")
            n_suggested += 1
        self.status_label.setText(
            f"{n_suggested} de {len(matches)} línea(s) sugerida(s) contra el catálogo de {lamp_name} -- "
            "revisa cada una antes de ajustar."
        )

    def _on_fit(self) -> None:
        wavelengths: list[float] = []
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 2)
            text = item.text().strip() if item else ""
            if not text:
                self.status_label.setText(f"Falta la longitud de onda en la fila {row + 1}.")
                return
            try:
                wavelengths.append(float(text))
            except ValueError:
                self.status_label.setText(f"Longitud de onda no numérica en la fila {row + 1}.")
                return

        pixels = [line.pixel for line in self._lines]
        degree = self.degree_spin.value()

        # Ajuste polinómico sobre unas pocas líneas como mucho -- igual
        # que el ajuste de WCS, no hace falta hilo de fondo.
        try:
            solution = fit_wavelength_solution(pixels, wavelengths, degree=degree)
        except ValueError as exc:
            self.status_label.setText(f"Error: {exc}")
            return

        self.status_label.setText(f"Solución ajustada: RMS={solution.rms_residual:.4f} con {len(pixels)} línea(s).")
        table = Table(
            columns=("line", "pixel", "wavelength", "residual"),
            units=("", "px", "", ""),
            rows=tuple((i + 1, p, w, float(r)) for i, (p, w, r) in enumerate(zip(pixels, wavelengths, solution.residuals))),
        )
        lamp_name = self.lamp_combo.currentText()
        record = WavelengthCalibrationRecord(
            solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=len(pixels),
            lamp_name=None if lamp_name == "(sin especificar)" else lamp_name,
        )
        self._last_record = record
        self.fitted.emit(solution, table, record)
        self.accept()

    def _on_save_profile(self) -> None:
        if self._last_record is None:
            self.status_label.setText(
                "Ajusta primero una solución por líneas (\"Ajustar solución\") -- solo esa se puede "
                "guardar como perfil, no una ya reutilizada de otro perfil."
            )
            return
        name, ok = QInputDialog.getText(self, "Guardar perfil de calibración espectral", "Nombre de la configuración de instrumento:")
        name = name.strip()
        if not ok or not name:
            return
        profile = profile_from_record(name, self._last_record, reference_spectrum=self._spectrum)
        self.profile_store.save(profile)
        if self.profile_combo.findText(name) < 0:
            self.profile_combo.addItem(name)
        self.profile_combo.setCurrentText(name)
        self.status_label.setText(f"Perfil «{name}» guardado.")

    def _selected_profile(self):
        name = self.profile_combo.currentText()
        if name == _NO_PROFILE:
            self.status_label.setText("Elige un perfil de instrumento guardado antes de reutilizarlo.")
            return None
        profile = self.profile_store.load_all().get(name)
        if profile is None:
            self.status_label.setText(f"El perfil «{name}» ya no existe -- vuelve a guardarlo si hace falta.")
            return None
        return profile

    def _on_use_profile(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        record = profile.to_record()
        self.status_label.setText(
            f"Perfil «{profile.name}» reutilizado tal cual: RMS original={record.solution.rms_residual:.4f} "
            f"con {record.n_lines_used} línea(s) (sin recalcular nada en esta imagen)."
        )
        self._last_record = None  # una solución reutilizada no se puede volver a "guardar como perfil" sin más evidencia
        self.fitted.emit(record.solution, _EMPTY_LINE_TABLE, record)
        self.accept()

    def _on_reidentify_offset(self) -> None:
        profile = self._selected_profile()
        if profile is None:
            return
        if self._spectrum is None:
            self.status_label.setText("No hay espectro de esta imagen con el que correlacionar el perfil.")
            return
        try:
            record = reidentify_profile_offset(profile, self._spectrum)
        except ValueError as exc:
            self.status_label.setText(f"No se pudo recalcular el offset: {exc}")
            return
        self.status_label.setText(
            f"Perfil «{profile.name}»: desplazamiento global recalculado a "
            f"{record.solution.reference_pixel_shift:.2f} px. AVISO: un cambio mecánico/térmico real del "
            "instrumento puede haber desplazado el espectro de una forma que esta correlación no detecta."
        )
        self._last_record = None
        self.fitted.emit(record.solution, _EMPTY_LINE_TABLE, record)
        self.accept()
