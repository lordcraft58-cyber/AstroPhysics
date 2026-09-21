"""`extended_extraction.py`: extracción por suma simple sobre una región
espacial FIJA (§27) -- nunca por extracción óptima (Horne 1986), que
asume un perfil de fuente puntual.

Convención de `SpatialRegion`: `row_start`/`row_end` son AMBOS inclusive
(rango cerrado) -- por eso, cuando el helper de este archivo genera el
objeto con la convención de slice de Python `data[lo:hi]` (que excluye
`hi`), la región equivalente usa `row_end=hi - 1`.
"""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.extended_extraction import (
    SpatialRegion,
    extract_extended_region,
    extract_multi_region,
)
from astrophysics_suite.spectroscopy.trace import SkyWindow


def _flat_nebula_image(*, height=60, width=200, object_rows=(15, 45), object_level=100.0, sky_level=10.0, seed=1):
    """Emisión "extendida" real: nivel espacialmente PLANO (no un pico
    gaussiano) entre `object_rows` (convención de slice de Python: `lo`
    inclusive, `hi` exclusive), sobre un cielo uniforme -- justo el caso
    que un perfil de fuente puntual normalizado a un pico describiría
    mal."""
    rng = np.random.default_rng(seed)
    data = np.full((height, width), sky_level) + rng.normal(0, 0.5, (height, width))
    lo, hi = object_rows
    data[lo:hi, :] += object_level
    uncertainty = np.sqrt(np.clip(data, a_min=1.0, a_max=None))
    return data, uncertainty


def test_extracts_a_flat_extended_region_close_to_the_true_total_flux():
    lo, hi = 15, 45
    data, uncertainty = _flat_nebula_image(object_rows=(lo, hi), object_level=100.0, sky_level=10.0)
    region = SpatialRegion(row_start=float(lo), row_end=float(hi - 1))
    sky_windows = (SkyWindow(offset_px=-20.0, half_width_px=4.0), SkyWindow(offset_px=20.0, half_width_px=4.0))

    result = extract_extended_region(data, uncertainty, region, sky_windows=sky_windows)

    n_rows = hi - lo
    expected_flux = 100.0 * n_rows
    valid_flux = result.flux[result.valid]
    assert np.all(np.isfinite(valid_flux))
    assert np.median(valid_flux) == pytest.approx(expected_flux, rel=0.02)


def test_rejects_sky_windows_that_overlap_a_wide_region():
    data, uncertainty = _flat_nebula_image(object_rows=(15, 45))
    # región muy ancha (semiancho ~14.5 px) -- la ventana de cielo por
    # defecto (offset ±10, semiancho 4) cae DENTRO de la región
    region = SpatialRegion(row_start=15.0, row_end=44.0)

    with pytest.raises(ValueError, match="solapa"):
        extract_extended_region(data, uncertainty, region)


def test_empty_sky_windows_leaves_every_column_invalid_rather_than_inventing_a_zero_background():
    """Documenta el comportamiento REAL heredado de `estimate_sky_
    background`/`extract_sum` (ver docstring del módulo): sin ninguna
    ventana de cielo no hay evidencia real de fondo, así que la columna
    entera queda inválida -- `sky_windows=()` NUNCA es una forma de decir
    "usa fondo cero", ni aquí ni en el resto del proyecto."""
    data, uncertainty = _flat_nebula_image(object_rows=(15, 45), sky_level=0.0)
    region = SpatialRegion(row_start=15.0, row_end=44.0)

    result = extract_extended_region(data, uncertainty, region, sky_windows=())

    assert not np.any(result.valid)


def test_region_requires_row_end_at_least_row_start():
    SpatialRegion(row_start=30.0, row_end=30.0)  # una sola fila: válido
    with pytest.raises(ValueError):
        SpatialRegion(row_start=30.0, row_end=10.0)


def test_extract_multi_region_resolves_two_independent_bins_of_the_same_nebula():
    lo, hi = 20, 60
    data, uncertainty = _flat_nebula_image(height=80, width=150, object_rows=(lo, hi), object_level=80.0, sky_level=5.0)
    sky_windows = (SkyWindow(offset_px=-40.0, half_width_px=4.0), SkyWindow(offset_px=40.0, half_width_px=4.0))
    core = SpatialRegion(row_start=20.0, row_end=39.0, label="core")  # 20 filas
    edge = SpatialRegion(row_start=40.0, row_end=59.0, label="edge")  # 20 filas

    result = extract_multi_region(data, uncertainty, [core, edge], sky_windows=sky_windows)

    assert len(result.extractions) == 2
    assert not result.failures
    assert result.extractions[0].region.label == "core"
    assert result.extractions[1].region.label == "edge"
    for extraction in result.extractions:
        valid_flux = extraction.spectrum.flux[extraction.spectrum.valid]
        assert np.median(valid_flux) == pytest.approx(80.0 * 20, rel=0.02)


def test_extract_multi_region_reports_failures_without_stopping_the_batch():
    lo, hi = 10, 30
    data, uncertainty = _flat_nebula_image(height=40, width=100, object_rows=(lo, hi), object_level=50.0, sky_level=10.0)
    sky_windows = (SkyWindow(offset_px=-20.0, half_width_px=4.0), SkyWindow(offset_px=20.0, half_width_px=4.0))
    good = SpatialRegion(row_start=13.0, row_end=17.0, label="good")  # dentro del objeto, lejos de sus bordes
    out_of_image = SpatialRegion(row_start=100.0, row_end=120.0, label="fuera_de_imagen")

    result = extract_multi_region(data, uncertainty, [good, out_of_image], sky_windows=sky_windows)

    assert len(result.extractions) == 1
    assert result.extractions[0].region.label == "good"
    assert len(result.failures) == 1
    assert result.failures[0].region.label == "fuera_de_imagen"
    assert "fuera de la imagen" in result.failures[0].reason


def test_rejects_mismatched_data_and_uncertainty_shapes():
    data, uncertainty = _flat_nebula_image()
    region = SpatialRegion(row_start=15.0, row_end=44.0)
    with pytest.raises(ValueError):
        extract_extended_region(data, uncertainty[:-1], region, sky_windows=())
