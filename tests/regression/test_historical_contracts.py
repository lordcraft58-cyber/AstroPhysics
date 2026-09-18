"""Regresión de los dos defectos históricos citados explícitamente por el
usuario (docs/audit/01-AUDITORIA-TECNICA-FASE1.md, seccion 3.3):

1. `stack_multiband()` debe usar el contrato real de `estimate_background()`
   -- `Background.bkg` / `Background.rms` -- y NO un atributo inexistente
   como `bg.background`. El bug histórico habría lanzado AttributeError en
   tiempo de ejecución al primer intento de apilar bandas.

2. `measure_proper_motion()` debe tratar el retorno de
   `detect_point_sources()` como lo que realmente es -- un `np.ndarray`
   (N, 3) = [x, y, flux] -- y no como una lista de diccionarios. El bug
   histórico habría lanzado TypeError/KeyError al intentar indexar por
   clave un array de NumPy.

Ambos ya estaban corregidos en el snapshot v57.0.0 auditado (verificado
por lectura de código en la Fase 1), pero no existía ningún test que lo
garantizara hacia el futuro. Estos tests ejecutan el camino real
(no solo leen el código fuente) contra datos sintéticos, para que una
regresión futura falle aquí en vez de en producción.
"""
from __future__ import annotations

import numpy as np
import pytest


def _gaussian_star_field(shape, positions, amplitude=800.0, sigma=1.8, background=100.0, seed=1234):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, float(background), dtype=np.float32)
    for x, y in positions:
        field += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def test_background_contract_is_bkg_and_rms(aps):
    """`estimate_background` debe exponer `.bkg`/`.rms` (nunca `.background`)."""
    data = _gaussian_star_field((64, 64), positions=[(32, 32)])
    bg = aps.estimate_background(data)
    assert hasattr(bg, "bkg"), "Background debe exponer .bkg (contrato usado por todo el pipeline)"
    assert hasattr(bg, "rms"), "Background debe exponer .rms"
    assert not hasattr(bg, "background"), (
        "Background no debe exponer .background -- ese fue el atributo incorrecto del bug "
        "histórico de stack_multiband (confundido con el atributo interno de "
        "photutils.background.Background2D)."
    )


def test_detect_point_sources_returns_nx3_array(aps):
    positions = [(20, 20), (40, 45)]
    data = _gaussian_star_field((64, 64), positions=positions)
    bg = aps.estimate_background(data)
    sources = aps.detect_point_sources(data, bg, fwhm_px=3.0, threshold_sigma=3.0)

    assert isinstance(sources, np.ndarray), "detect_point_sources debe devolver un np.ndarray"
    assert sources.ndim == 2 and sources.shape[1] == 3, (
        f"Contrato Nx3 [x, y, flux] violado: shape={sources.shape}"
    )
    with pytest.raises((TypeError, IndexError)):
        sources[0]["x"]  # un array NumPy nunca debe indexarse como si fuera un dict


def test_stack_multiband_uses_real_background_contract(aps, tmp_path):
    """Regresión directa: si stack_multiband usara bg.background en vez de
    bg.bkg, esta llamada lanzaría AttributeError antes de llegar al return."""
    oiii = _gaussian_star_field((48, 48), positions=[(24, 24)])
    ha = _gaussian_star_field((48, 48), positions=[(24, 24)], seed=99)

    oiii_path = tmp_path / "target_OIII.fits"
    ha_path = tmp_path / "target_HALPHA.fits"
    aps._write_minimal_fits_2d(oiii_path, oiii)
    aps._write_minimal_fits_2d(ha_path, ha)

    out_path = tmp_path / "cube.fits"
    result = aps.stack_multiband([str(oiii_path), str(ha_path)], str(out_path), normalize=True)

    assert "error" not in result, f"stack_multiband falló: {result.get('error')}"
    assert result["bands"] == ["OIII", "HA"]
    assert result["n_bands"] == 2
    assert result["state"] == "OBSERVABLE"


def test_measure_proper_motion_nx3_contract(aps, tmp_path):
    """Regresión directa: si measure_proper_motion tratara el retorno de
    detect_point_sources como lista de dicts, esta llamada lanzaría
    TypeError al intentar indexar el array por clave."""
    shape = (96, 96)
    positions_epoch1 = [(20, 20), (35, 60), (60, 30), (80, 90), (100 - 5, 55), (45, 100 - 5)]
    dx, dy = 2.4, -1.7
    positions_epoch2 = [(x + dx, y + dy) for x, y in positions_epoch1]

    epoch1 = _gaussian_star_field(shape, positions_epoch1, seed=1)
    epoch2 = _gaussian_star_field(shape, positions_epoch2, seed=2)

    p1 = tmp_path / "epoch1.fits"
    p2 = tmp_path / "epoch2.fits"
    aps._write_minimal_fits_2d(p1, epoch1)
    aps._write_minimal_fits_2d(p2, epoch2)

    result = aps.measure_proper_motion(str(p1), str(p2), pixel_scale_arcsec=1.0, time_baseline_yr=1.0)

    assert "error" not in result, f"measure_proper_motion falló: {result.get('error')}"
    assert result["n_stars_matched"] >= 3
    # El desplazamiento medido debe aproximar el desplazamiento sintético inyectado.
    assert abs(result["median_dx_px"] - dx) < 0.5
    assert abs(result["median_dy_px"] - dy) < 0.5
