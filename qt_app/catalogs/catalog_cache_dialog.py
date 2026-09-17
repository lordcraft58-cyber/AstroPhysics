"""Descarga del catálogo de un campo a disco, para trabajar sin red y sin
machacar el servicio público -- ver
`astrophysics_suite.catalogs.local_cache` para el motor real y la ruta
exacta donde se guarda.

Dos motivos reales, medidos: (1) Discovery consulta el catálogo UNA VEZ
POR DETECCIÓN -- en los lights reales de M 31 eso son cientos de
consultas por análisis; con el campo descargado son cero. (2) Sin
internet, ninguna detección se puede comprobar y todas quedan en
"revisión"; con el campo descargado, el análisis identifica igual.

La posición y el radio se pre-rellenan desde el WCS real de la imagen
activa (centro del campo y su diagonal), o desde el nombre del objeto
vía SIMBAD -- nunca se inventa un campo por defecto."""
from __future__ import annotations

from PySide6.QtWidgets import (
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
)

from astrophysics_suite.catalogs.local_cache import CatalogCache, download_field_to_cache
from astrophysics_suite.catalogs.simbad import resolve_object_coordinates
from qt_app.workers import CallableWorker


def field_centre_and_radius_from_wcs(wcs, shape) -> tuple[float, float, float] | None:
    """`(ra, dec, radio_arcsec)` que cubre TODA la imagen: el centro real
    del campo y la mitad de su diagonal, con un 10% de margen para que el
    borde quede cubierto de verdad. `None` si la imagen no tiene WCS --
    nunca se adivina un campo."""
    if wcs is None or shape is None or len(shape) < 2:
        return None
    height, width = float(shape[0]), float(shape[1])
    try:
        centre_ra, centre_dec = wcs.all_pix2world(width / 2.0, height / 2.0, 0)
        corner_ra, corner_dec = wcs.all_pix2world(0.0, 0.0, 0)
    except Exception:
        return None

    import math

    ra1, dec1 = math.radians(float(centre_ra)), math.radians(float(centre_dec))
    ra2, dec2 = math.radians(float(corner_ra)), math.radians(float(corner_dec))
    delta_ra = ra2 - ra1
    numerator = math.hypot(
        math.cos(dec2) * math.sin(delta_ra),
        math.cos(dec1) * math.sin(dec2) - math.sin(dec1) * math.cos(dec2) * math.cos(delta_ra),
    )
    denominator = math.sin(dec1) * math.sin(dec2) + math.cos(dec1) * math.cos(dec2) * math.cos(delta_ra)
    radius_arcsec = math.degrees(math.atan2(numerator, denominator)) * 3600.0
    return float(centre_ra), float(centre_dec), radius_arcsec * 1.1


class CatalogCacheDialog(QDialog):
    """Descarga el catálogo de un campo y muestra el estado real de la
    caché en disco."""

    def __init__(self, wcs=None, shape=None, object_name: str = "", parent=None):
        super().__init__(parent)
        self._worker: CallableWorker | None = None
        self._simbad_worker: CallableWorker | None = None
        self.cache = CatalogCache("gaia")

        self.setWindowTitle("Descargar catálogo del campo (Gaia)")
        self.resize(520, 340)

        layout = QVBoxLayout(self)
        hint = QLabel(
            "Descarga UNA vez las fuentes de Gaia de este campo a tu ordenador. Después, los análisis las "
            "consultan desde disco: funcionan sin internet y sin hacer cientos de consultas al servicio."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)

        object_row = QHBoxLayout()
        self.object_name_edit = QLineEdit()
        self.object_name_edit.setText(object_name)
        self.object_name_edit.setPlaceholderText("Nombre real del objeto (p. ej. \"M 31\")...")
        self.simbad_button = QPushButton("Buscar en SIMBAD...")
        self.simbad_button.clicked.connect(self._on_simbad_lookup)
        object_row.addWidget(self.object_name_edit)
        object_row.addWidget(self.simbad_button)

        form = QFormLayout()
        form.addRow("Objeto", object_row)

        self.ra_spin = QDoubleSpinBox()
        self.ra_spin.setRange(0.0, 360.0)
        self.ra_spin.setDecimals(6)
        self.dec_spin = QDoubleSpinBox()
        self.dec_spin.setRange(-90.0, 90.0)
        self.dec_spin.setDecimals(6)
        self.radius_spin = QDoubleSpinBox()
        self.radius_spin.setRange(0.1, 300.0)
        self.radius_spin.setDecimals(2)
        self.radius_spin.setValue(30.0)
        self.radius_spin.setSuffix(" '")
        self.mag_spin = QDoubleSpinBox()
        self.mag_spin.setRange(5.0, 22.0)
        self.mag_spin.setDecimals(1)
        self.mag_spin.setValue(20.0)

        field = field_centre_and_radius_from_wcs(wcs, shape)
        if field is not None:
            centre_ra, centre_dec, radius_arcsec = field
            self.ra_spin.setValue(centre_ra)
            self.dec_spin.setValue(centre_dec)
            self.radius_spin.setValue(max(0.1, radius_arcsec / 60.0))

        form.addRow("RA (grados)", self.ra_spin)
        form.addRow("Dec (grados)", self.dec_spin)
        form.addRow("Radio", self.radius_spin)
        form.addRow("Magnitud G límite", self.mag_spin)
        layout.addLayout(form)

        self.cache_state_label = QLabel(self.cache.describe())
        self.cache_state_label.setWordWrap(True)
        layout.addWidget(self.cache_state_label)

        self.status_label = QLabel(
            "Listo." if field is not None
            else "La imagen activa no tiene WCS: escribe el objeto y búscalo en SIMBAD, o pon RA/Dec a mano."
        )
        self.status_label.setWordWrap(True)
        layout.addWidget(self.status_label)

        buttons_row = QHBoxLayout()
        self.download_button = QPushButton("Descargar campo")
        self.download_button.clicked.connect(self._on_download)
        self.clear_button = QPushButton("Vaciar caché")
        self.clear_button.clicked.connect(self._on_clear)
        buttons_row.addWidget(self.download_button)
        buttons_row.addWidget(self.clear_button)
        layout.addLayout(buttons_row)

        self.button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Close)
        self.button_box.rejected.connect(self.reject)
        layout.addWidget(self.button_box)

    # ------------------------------------------------------------ SIMBAD
    def _on_simbad_lookup(self) -> None:
        name = self.object_name_edit.text().strip()
        if not name:
            self.status_label.setText("Escribe primero el nombre del objeto.")
            return
        self.simbad_button.setEnabled(False)
        self.status_label.setText(f"Consultando SIMBAD para \"{name}\"...")
        self._simbad_worker = CallableWorker(lambda: resolve_object_coordinates(name), self)
        self._simbad_worker.finished_ok.connect(self._on_simbad_resolved)
        self._simbad_worker.failed.connect(self._on_simbad_failed)
        self._simbad_worker.start()

    def _on_simbad_resolved(self, resolved) -> None:
        self.simbad_button.setEnabled(True)
        if resolved is None:
            self.status_label.setText(
                f"SIMBAD no reconoció \"{self.object_name_edit.text().strip()}\" -- comprueba el nombre o pon RA/Dec a mano."
            )
            return
        ra, dec, source = resolved
        self.ra_spin.setValue(ra)
        self.dec_spin.setValue(dec)
        self.status_label.setText(f"Coordenadas de {source}: RA={ra:.6f}, Dec={dec:.6f}.")

    def _on_simbad_failed(self, message: str) -> None:
        self.simbad_button.setEnabled(True)
        self.status_label.setText(f"La consulta a SIMBAD falló: {message}")

    # ---------------------------------------------------------- descarga
    def _on_download(self) -> None:
        ra, dec = self.ra_spin.value(), self.dec_spin.value()
        radius_arcsec = self.radius_spin.value() * 60.0
        mag_limit = self.mag_spin.value()
        self.download_button.setEnabled(False)
        self.status_label.setText(
            f"Descargando Gaia en un radio de {self.radius_spin.value():.1f}' alrededor de RA={ra:.5f} Dec={dec:.5f}... "
            f"(un campo grande puede tardar un rato)"
        )
        self._worker = CallableWorker(
            lambda: download_field_to_cache(ra, dec, radius_arcsec, mag_limit=mag_limit, cache=self.cache), self
        )
        self._worker.finished_ok.connect(self._on_download_finished)
        self._worker.failed.connect(self._on_download_failed)
        self._worker.start()

    def _on_download_finished(self, result) -> None:
        self.download_button.setEnabled(True)
        ok, detail = result
        self.status_label.setText(detail)
        self.cache_state_label.setText(self.cache.describe())

    def _on_download_failed(self, message: str) -> None:
        self.download_button.setEnabled(True)
        self.status_label.setText(f"La descarga falló: {message}")

    def _on_clear(self) -> None:
        self.cache.clear()
        self.cache_state_label.setText(self.cache.describe())
        self.status_label.setText("Caché vaciada -- los análisis volverán a consultar el catálogo por red.")
