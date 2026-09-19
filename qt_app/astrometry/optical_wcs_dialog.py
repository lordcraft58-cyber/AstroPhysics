"""WCS desde la óptica real del usuario -- su cámara sobre su telescopio
-- en vez de intentar descubrirlo resolviendo la placa contra el cielo.

Mismo espíritu que una calculadora de campo (astronomy.tools y
equivalentes): se elige la cámara, se introduce la focal (y la abertura
si se quiere la relación focal), y el diálogo enseña en vivo la escala
de placa, el campo cubierto y el muestreo REALES antes de construir
nada.

Tres disciplinas de honestidad que este diálogo mantiene:
  1. La cabecera FITS/XISF del propio archivo manda sobre el catálogo
     interno: si el archivo dice `XPIXSZ`/`FOCALLEN`, se rellenan solos
     y, si el catálogo de la cámara elegida los contradice, se AVISA en
     vez de sobrescribir en silencio.
  2. La geometría de la imagen cargada manda sobre la del catálogo -- una
     imagen recortada o demosaicada por SuperPixel ya no tiene la
     resolución nominal del sensor, y eso cambia la escala real.
  3. El centro y la orientación no se adivinan: si el usuario no los
     sabe, el WCS resultante será tan bueno como sus datos, y así se
     etiqueta (solución declarada, no ajustada -- ver
     `astrometry/optical_wcs.py::is_optical_wcs`).
"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
)

from astrophysics_suite.astrometry.optical_wcs import build_wcs_from_optics
from astrophysics_suite.catalogs.simbad import resolve_object_coordinates
from astrophysics_suite.instruments.cameras import BUILTIN_CAMERAS, find_camera
from astrophysics_suite.instruments.header import read_header_optics
from astrophysics_suite.instruments.optics import OpticalSetup
from qt_app.workers import CallableWorker

CUSTOM_CAMERA_OPTION = "Personalizada (introducir a mano)"
_TYPICAL_SEEING_ARCSEC = 3.0


class OpticalWCSDialog(QDialog):
    built = Signal(object, object)
    """Emite `(WCSSolution, OpticalSetup)` al construir el WCS."""

    def __init__(self, image_shape: tuple[int, int], header: dict | None, parent=None):
        super().__init__(parent)
        self.setWindowTitle("WCS desde la óptica (cámara + focal)")
        self.resize(560, 640)
        self._image_height, self._image_width = image_shape
        self._header_optics = read_header_optics(header or {})
        self._simbad_worker: CallableWorker | None = None

        layout = QVBoxLayout(self)
        hint = QLabel(
            "La escala del campo se deduce de tu equipo real -- no hace falta resolver la placa. "
            "Lo único que el programa no puede saber es a dónde apuntabas y con qué giro: eso lo pones tú."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        equipment = QFormLayout()
        self.camera_combo = QComboBox()
        self.camera_combo.addItems([c.name for c in BUILTIN_CAMERAS])
        self.camera_combo.addItem(CUSTOM_CAMERA_OPTION)
        self.camera_combo.currentTextChanged.connect(self._on_camera_changed)
        equipment.addRow("Cámara", self.camera_combo)

        self.pixel_spin = QDoubleSpinBox()
        self.pixel_spin.setRange(0.1, 50.0)
        self.pixel_spin.setDecimals(3)
        self.pixel_spin.setSuffix(" µm")
        self.pixel_spin.valueChanged.connect(self._refresh)
        equipment.addRow("Tamaño de píxel", self.pixel_spin)

        self.focal_spin = QDoubleSpinBox()
        self.focal_spin.setRange(1.0, 50000.0)
        self.focal_spin.setDecimals(1)
        self.focal_spin.setSuffix(" mm")
        self.focal_spin.valueChanged.connect(self._refresh)
        equipment.addRow("Longitud focal", self.focal_spin)

        self.aperture_spin = QDoubleSpinBox()
        self.aperture_spin.setRange(0.0, 5000.0)
        self.aperture_spin.setDecimals(1)
        self.aperture_spin.setSuffix(" mm")
        self.aperture_spin.setSpecialValueText("(sin indicar)")
        self.aperture_spin.valueChanged.connect(self._refresh)
        equipment.addRow("Abertura (opcional)", self.aperture_spin)

        self.binning_spin = QSpinBox()
        self.binning_spin.setRange(1, 8)
        self.binning_spin.valueChanged.connect(self._refresh)
        equipment.addRow("Binning", self.binning_spin)
        layout.addLayout(equipment)

        self.computed_label = QLabel("")
        self.computed_label.setWordWrap(True)
        layout.addWidget(self.computed_label)

        self.warning_label = QLabel("")
        self.warning_label.setWordWrap(True)
        self.warning_label.setObjectName("Muted")
        layout.addWidget(self.warning_label)

        pointing = QFormLayout()
        object_row = QHBoxLayout()
        self.object_edit = QLineEdit()
        self.object_edit.setPlaceholderText("p. ej. M 31")
        object_row.addWidget(self.object_edit, 1)
        self.simbad_button = QPushButton("Buscar en SIMBAD...")
        self.simbad_button.clicked.connect(self._on_simbad_lookup)
        object_row.addWidget(self.simbad_button)
        pointing.addRow("Objeto apuntado", object_row)

        self.ra_spin = QDoubleSpinBox()
        self.ra_spin.setRange(0.0, 360.0)
        self.ra_spin.setDecimals(6)
        self.ra_spin.setSuffix("°")
        pointing.addRow("RA del centro", self.ra_spin)

        self.dec_spin = QDoubleSpinBox()
        self.dec_spin.setRange(-90.0, 90.0)
        self.dec_spin.setDecimals(6)
        self.dec_spin.setSuffix("°")
        pointing.addRow("Dec del centro", self.dec_spin)

        self.rotation_spin = QDoubleSpinBox()
        self.rotation_spin.setRange(-360.0, 360.0)
        self.rotation_spin.setDecimals(2)
        self.rotation_spin.setSuffix("°")
        pointing.addRow("Rotación (0 = norte arriba)", self.rotation_spin)

        self.mirrored_check = QCheckBox("Imagen reflejada (este a la derecha)")
        pointing.addRow(self.mirrored_check)
        layout.addLayout(pointing)

        self.simbad_status_label = QLabel("")
        self.simbad_status_label.setObjectName("Muted")
        self.simbad_status_label.setWordWrap(True)
        layout.addWidget(self.simbad_status_label)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Cancel)
        self.build_button = self.button_box.addButton("Construir WCS", QDialogButtonBox.ButtonRole.AcceptRole)
        self.build_button.clicked.connect(self._on_build)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

        self._prefill_from_header()
        self._refresh()

    # ---------------------------------------------------------------- relleno desde la cabecera real
    def _prefill_from_header(self) -> None:
        optics = self._header_optics
        if optics.matched_camera is not None:
            self.camera_combo.setCurrentText(optics.matched_camera.name)
        elif optics.camera_name:
            self.camera_combo.setCurrentText(CUSTOM_CAMERA_OPTION)

        if optics.pixel_size_um is not None:
            self.pixel_spin.setValue(optics.pixel_size_um)
        elif optics.matched_camera is not None:
            self.pixel_spin.setValue(optics.matched_camera.pixel_size_um)
        else:
            self.pixel_spin.setValue(3.76)

        if optics.focal_length_mm is not None:
            self.focal_spin.setValue(optics.focal_length_mm)
        if optics.binning is not None:
            self.binning_spin.setValue(optics.binning)
        if optics.center_ra_deg is not None:
            self.ra_spin.setValue(optics.center_ra_deg)
        if optics.center_dec_deg is not None:
            self.dec_spin.setValue(optics.center_dec_deg)
        if optics.object_name:
            self.object_edit.setText(optics.object_name)

    def _on_camera_changed(self, name: str) -> None:
        camera = find_camera(name)
        if camera is not None:
            self.pixel_spin.setValue(camera.pixel_size_um)
        self._refresh()

    # ---------------------------------------------------------------- estado derivado en vivo
    def current_setup(self) -> OpticalSetup:
        aperture = self.aperture_spin.value()
        return OpticalSetup(
            camera_name=self.camera_combo.currentText(),
            pixel_size_um=self.pixel_spin.value(),
            # la geometría REAL de la imagen cargada, no la nominal del
            # sensor: un recorte o un demosaico ya la han cambiado.
            width_px=self._image_width,
            height_px=self._image_height,
            focal_length_mm=self.focal_spin.value(),
            aperture_mm=aperture if aperture > 0 else None,
            binning=self.binning_spin.value(),
        )

    def _refresh(self) -> None:
        setup = self.current_setup()
        scale = setup.pixel_scale_arcsec
        width_deg, height_deg = setup.field_of_view_deg
        parts = [
            f"<b>Escala: {scale:.4f} \"/px</b>",
            f"Campo: {width_deg * 60:.1f}' × {height_deg * 60:.1f}' ({width_deg:.3f}° × {height_deg:.3f}°)",
        ]
        ratio = setup.focal_ratio
        if ratio is not None:
            parts.append(f"Relación focal: f/{ratio:.1f} · límite de Dawes {setup.dawes_limit_arcsec:.2f}\"")
        sampling = setup.describe_sampling(_TYPICAL_SEEING_ARCSEC)
        if sampling is not None:
            parts.append(f"Muestreo: {sampling}")
        self.computed_label.setText("<br>".join(parts))
        self.warning_label.setText("<br>".join(self._warnings(setup)))

    def _warnings(self, setup: OpticalSetup) -> list[str]:
        warnings: list[str] = []
        optics = self._header_optics

        if optics.pixel_size_um is not None and abs(optics.pixel_size_um - setup.pixel_size_um) > 0.01:
            warnings.append(
                f"⚠ La cabecera del archivo dice {optics.pixel_size_um:.3f} µm por píxel y aquí hay "
                f"{setup.pixel_size_um:.3f} µm. La cabecera la escribió tu cámara real: créela a ella."
            )
        if optics.focal_length_mm is not None and abs(optics.focal_length_mm - setup.focal_length_mm) > 0.5:
            warnings.append(
                f"⚠ La cabecera declara {optics.focal_length_mm:.1f} mm de focal y aquí hay "
                f"{setup.focal_length_mm:.1f} mm."
            )

        camera = find_camera(self.camera_combo.currentText())
        if camera is not None and self._image_width and camera.width_px != self._image_width:
            factor = camera.width_px / self._image_width
            extra = ""
            if abs(factor - 2.0) < 0.05:
                extra = " Es justo la mitad: típico de un demosaico SuperPixel/luminancia, que DUPLICA la escala real."
            warnings.append(
                f"⚠ La imagen cargada mide {self._image_width}×{self._image_height} px y el sensor de "
                f"«{camera.name}» es de {camera.width_px}×{camera.height_px} px.{extra}"
            )
        return warnings

    # ---------------------------------------------------------------- SIMBAD
    def _on_simbad_lookup(self) -> None:
        name = self.object_edit.text().strip()
        if not name:
            self.simbad_status_label.setText("Escribe el nombre real del objeto (p. ej. \"M 31\") antes de buscar.")
            return
        self.simbad_button.setEnabled(False)
        self.simbad_status_label.setText(f"Consultando SIMBAD por «{name}»...")

        def run():
            return resolve_object_coordinates(name)

        self._simbad_worker = CallableWorker(run, self)
        self._simbad_worker.finished_ok.connect(self._on_simbad_resolved)
        self._simbad_worker.failed.connect(self._on_simbad_failed)
        self._simbad_worker.start()

    def _on_simbad_resolved(self, result) -> None:
        self.simbad_button.setEnabled(True)
        if result is None:
            self.simbad_status_label.setText(
                f"SIMBAD no pudo resolver «{self.object_edit.text().strip()}» -- comprueba el nombre "
                f"(o la conectividad), o introduce la posición a mano."
            )
            return
        ra, dec, source = result
        self.ra_spin.setValue(ra)
        self.dec_spin.setValue(dec)
        self.simbad_status_label.setText(f"Posición obtenida de {source}: RA={ra:.6f}° Dec={dec:.6f}°.")

    def _on_simbad_failed(self, message: str) -> None:
        self.simbad_button.setEnabled(True)
        self.simbad_status_label.setText(f"No se pudo consultar SIMBAD: error interno inesperado -- {message}")

    # ---------------------------------------------------------------- construcción
    def _on_build(self) -> None:
        setup = self.current_setup()
        try:
            solution = build_wcs_from_optics(
                center_ra_deg=self.ra_spin.value(),
                center_dec_deg=self.dec_spin.value(),
                pixel_scale_arcsec=setup.pixel_scale_arcsec,
                image_shape=(self._image_height, self._image_width),
                rotation_deg=self.rotation_spin.value(),
                mirrored=self.mirrored_check.isChecked(),
            )
        except ValueError as exc:
            self.simbad_status_label.setText(f"No se pudo construir el WCS: {exc}")
            return
        self.built.emit(solution, setup)
        self.accept()
