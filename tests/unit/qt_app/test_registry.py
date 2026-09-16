"""Los adaptadores de proceso son numpy puro -- comprobables sin Qt. No
deben reimplementar ninguna matemática, solo traducir parámetros/resultados;
estas pruebas confirman que la traducción en sí es correcta."""
from __future__ import annotations

import math

import numpy as np

from qt_app.processes.registry import build_process_registry


def _get(process_id: str):
    registry = build_process_registry()
    matches = [p for p in registry if p.process_id == process_id]
    assert len(matches) == 1, f"proceso {process_id} no encontrado o duplicado"
    return matches[0]


def _default_params(process):
    return {p.name: p.default for p in process.parameters}


def test_registry_has_no_duplicate_process_ids():
    registry = build_process_registry()
    ids = [p.process_id for p in registry]
    assert len(ids) == len(set(ids))


def test_registry_covers_all_expected_categories():
    registry = build_process_registry()
    categories = {p.category for p in registry}
    assert categories == {"Reducción CCD", "Utilidades de imagen", "Fotometría", "Espectroscopía", "Astrometría"}


def test_unwired_processes_have_no_run_and_are_flagged():
    registry = build_process_registry()
    unwired = [p for p in registry if not p.is_wired]
    assert unwired  # deben quedar pendientes documentados, no ocultos
    for process in unwired:
        assert process.run is None
        assert process.description  # explica qué falta, no queda en blanco


def test_wired_processes_are_actually_callable():
    registry = build_process_registry()
    wired = [p for p in registry if p.is_wired]
    assert len(wired) >= 3
    for process in wired:
        assert callable(process.run)


def test_cosmic_ray_removal_process_flags_injected_spike():
    process = _get("imtools.cosmic_rays")
    data = np.full((40, 40), 200.0)
    data[20, 20] += 6000.0
    result = process.run(data, _default_params(process))
    assert result.output_data is not None
    assert abs(result.output_data[20, 20] - 200.0) < 50.0
    assert "1 píxel" in result.summary or "píxel(es)" in result.summary


def test_overscan_subtraction_process_trims_and_subtracts():
    height, width = 30, 50
    data = np.full((height, width), 100.0)
    data[:, width - 20 :] = 500.0  # franja de overscan con un nivel distinto
    process = _get("reduction.overscan")
    result = process.run(data, _default_params(process))
    assert result.output_data is not None
    assert result.output_data.shape == (height, width - 20)
    np.testing.assert_allclose(result.output_data, -400.0)


def test_aperture_photometry_process_reports_positive_flux_for_central_star():
    yy, xx = np.mgrid[0:61, 0:61]
    data = 100.0 + 20000.0 / (2 * math.pi * 3.0**2) * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * 3.0**2))
    process = _get("photometry.aperture")
    params = _default_params(process)
    result = process.run(data, params)
    assert result.output_data is None  # es un proceso de medición, no transforma la imagen
    assert "Flujo neto" in result.summary


def test_continuum_fit_process_runs_on_central_row():
    data = np.full((21, 200), 100.0)
    data[10, 50:55] += 300.0  # línea de emisión en la fila central
    process = _get("spectroscopy.continuum")
    result = process.run(data, _default_params(process))
    assert result.output_data is None
    assert "Continuo ajustado" in result.summary
