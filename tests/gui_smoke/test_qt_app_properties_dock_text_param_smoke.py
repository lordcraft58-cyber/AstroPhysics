"""Prueba de humo del nuevo tipo de parámetro "text" en `ParameterSpec`/
`PropertiesDock` (§19: hacía falta un campo de texto libre real para las
regiones de continuo manuales de "Ajuste de continuo" -- el formulario
genérico solo sabía construir float/int/bool/choice hasta ahora).

Requiere PySide6 y un display X -- se salta si no están disponibles.
"""
from __future__ import annotations

import numpy as np
import pytest

PySide6 = pytest.importorskip("PySide6", reason="PySide6 no instalado en este entorno")

from PySide6.QtWidgets import QApplication, QLineEdit  # noqa: E402

from qt_app.docks.properties_dock import PropertiesDock  # noqa: E402
from qt_app.processes.base import ParameterSpec, ProcessDefinition, ProcessResult  # noqa: E402


def _display_available() -> bool:
    try:
        app = QApplication.instance() or QApplication([])
    except Exception:
        return False
    return app is not None


pytestmark = pytest.mark.skipif(not _display_available(), reason="sin display X disponible (ni real ni Xvfb) o Qt no puede inicializar")


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance() or QApplication([])
    yield app


def _run_stub(data: np.ndarray, params: dict) -> ProcessResult:
    return ProcessResult(output_data=None, summary=f"regiones={params['regions']!r}")


def test_properties_dock_builds_a_real_line_edit_for_a_text_parameter(qapp):
    process = ProcessDefinition(
        process_id="test.text_param",
        name="Proceso de prueba",
        category="Prueba",
        description="",
        parameters=(ParameterSpec("regions", "Regiones", "text", "50-100"),),
        run=_run_stub,
    )
    dock = PropertiesDock()
    dock.set_process(process)

    widget = dock._param_widgets["regions"]
    assert isinstance(widget, QLineEdit)
    assert widget.text() == "50-100"


def test_properties_dock_apply_emits_the_edited_text_value(qapp):
    process = ProcessDefinition(
        process_id="test.text_param",
        name="Proceso de prueba",
        category="Prueba",
        description="",
        parameters=(ParameterSpec("regions", "Regiones", "text", ""),),
        run=_run_stub,
    )
    dock = PropertiesDock()
    dock.set_process(process)

    received: dict = {}
    dock.run_requested.connect(lambda process_id, params: received.update(process_id=process_id, params=params))

    widget = dock._param_widgets["regions"]
    widget.setText("10-20,30-40")
    dock._on_apply_clicked()

    assert received["process_id"] == "test.text_param"
    assert received["params"]["regions"] == "10-20,30-40"
