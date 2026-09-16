"""Prueba end-to-end (no simulada) del Detection Engine: escribe un FITS
sintético con fuentes puntuales inyectadas de posición conocida, lo carga
por `io.fits_loader.load_image` y confirma que `detect_point_sources`
las encuentra con `Detection` correctamente formados."""
from __future__ import annotations

import math

import numpy as np

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.detection.point_sources import detect_point_sources
from astrophysics_suite.io.fits_loader import load_image
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _synthetic_star_field(shape, positions, amplitude=900.0, sigma=1.8, background=100.0, seed=42):
    rng = np.random.default_rng(seed)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, float(background), dtype=np.float32)
    for x, y in positions:
        field += amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


def test_detect_point_sources_finds_injected_stars(tmp_path):
    positions = [(30, 30), (70, 45), (50, 80)]
    field = _synthetic_star_field((128, 128), positions)
    path = tmp_path / "field_OIII.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    loaded = load_image(str(path), band="OIII")
    detections = detect_point_sources(loaded, observation_id="OBS-0001", band="OIII", threshold_sigma=4.0)

    assert len(detections) >= len(positions)

    found_positions = {(round(d.position.x_px), round(d.position.y_px)) for d in detections}
    for x, y in positions:
        assert any(abs(fx - x) <= 1 and abs(fy - y) <= 1 for fx, fy in found_positions), (
            f"No se encontró ninguna detección cerca de ({x}, {y}); encontradas: {found_positions}"
        )

    for d in detections:
        assert d.observation_id == "OBS-0001"
        assert d.bands == ("OIII",)
        assert d.method == "DAOStarFinder"
        assert d.morphology.morphology_class is MorphologyClass.POINT_SOURCE
        assert d.morphology.area_px > 0
        assert d.morphology.elongation >= 1.0  # 1.0 = circular por convención (ver módulo)
        assert math.isfinite(d.peak_snr)
        # Sin WCS (FITS mínimo sintético): no se inventan coordenadas celestes.
        assert d.position.ra_deg is None
        assert d.position.dec_deg is None


def test_detect_point_sources_returns_serializable_detections(tmp_path):
    field = _synthetic_star_field((64, 64), [(32, 32)])
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field, pixel_scale_arcsec=1.0)

    loaded = load_image(str(path), band="HA")
    detections = detect_point_sources(loaded, observation_id="OBS-0002", band="HA")
    assert detections

    from astrophysics_suite.models.detection import Detection

    for d in detections:
        restored = Detection.from_dict(d.to_dict())
        assert restored == d
