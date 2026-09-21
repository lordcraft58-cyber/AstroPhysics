"""Selector de plano para un FITS con más de 2 ejes (cubo 3D/4D) --
equivalente propio, honesto, de la barra de "planos" de un visor de
cubos: `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL.load_fits` ya se niega
deliberadamente a elegir un plano por su cuenta (`AmbiguousCubeError`,
ver su docstring: "no seleccionar automáticamente el primer plano de un
FITS 3D/4D sin avisar"). Antes de este diálogo, esa negativa no tenía
ningún camino de vuelta desde la GUI -- un FITS 3D/4D simplemente no se
podía abrir nunca. Este diálogo pide los índices que `load_fits(...,
plane=...)` necesita, nunca elige uno por defecto."""
from __future__ import annotations

from PySide6.QtWidgets import QDialog, QDialogButtonBox, QFormLayout, QLabel, QSpinBox, QVBoxLayout


class CubePlaneDialog(QDialog):
    def __init__(self, shape: tuple[int, ...], parent=None):
        """`shape`: forma completa del HDU (convención numpy/astropy,
        último eje = X) tal como la devuelve
        `astrophysics_suite.io.fits_loader.probe_fits_shape`."""
        super().__init__(parent)
        self.setWindowTitle("Seleccionar plano del cubo")
        self._extra_axes = len(shape) - 2

        layout = QVBoxLayout(self)
        layout.addWidget(QLabel(f"Este FITS tiene forma {shape} ({len(shape)} ejes) -- no es una imagen 2D."))
        layout.addWidget(QLabel(f"Indica el índice de plano para cad{'a uno de los' if self._extra_axes > 1 else 'a'} {self._extra_axes} eje(s) sobrante(s):"))

        form = QFormLayout()
        self._spinboxes: list[QSpinBox] = []
        for axis_index in range(self._extra_axes):
            size = shape[axis_index]
            spin = QSpinBox()
            spin.setRange(0, max(size - 1, 0))
            spin.setValue(0)
            form.addRow(f"Eje {axis_index + 1} (tamaño {size})", spin)
            self._spinboxes.append(spin)
        layout.addLayout(form)

        button_box = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        button_box.accepted.connect(self.accept)
        button_box.rejected.connect(self.reject)
        layout.addWidget(button_box)

    def selected_plane(self) -> tuple[int, ...]:
        return tuple(spin.value() for spin in self._spinboxes)
