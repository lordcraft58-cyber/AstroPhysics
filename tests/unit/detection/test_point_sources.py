"""Prueba end-to-end (no simulada) del Detection Engine: escribe un FITS
sintético con fuentes puntuales inyectadas de posición conocida, lo carga
por `io.fits_loader.load_image` y confirma que `detect_point_sources`
las encuentra con `Detection` correctamente formados."""
from __future__ import annotations

import math

import numpy as np

from astrophysics_suite.core.enums import MorphologyClass
from astrophysics_suite.detection.point_sources import detect_point_sources, detect_point_sources_in_array
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


def test_detect_point_sources_ids_collide_across_images_of_the_same_observation_without_image_index(tmp_path):
    # Regresión documentada: `det_id` es una etiqueta de componente conexa
    # LOCAL a cada imagen (reinicia en cada llamada), así que sin
    # `image_index` dos imágenes de la MISMA Observation con el mismo
    # número de fuentes producen detection_id idénticos -- una colisión
    # real que sobrescribía en silencio la fuente de la primera imagen en
    # cualquier estructura indexada por detection_id (encontrada
    # ejecutando el pipeline multiépoca real).
    positions = [(30, 30), (70, 45)]
    field_a = _synthetic_star_field((128, 128), positions, seed=1)
    field_b = _synthetic_star_field((128, 128), positions, seed=2)
    path_a, path_b = tmp_path / "epoch_a.fits", tmp_path / "epoch_b.fits"
    _write_minimal_fits_2d(path_a, field_a, pixel_scale_arcsec=1.0)
    _write_minimal_fits_2d(path_b, field_b, pixel_scale_arcsec=1.0)

    detections_a = detect_point_sources(load_image(str(path_a), band="L"), observation_id="OBS-COLLIDE", band="L", threshold_sigma=4.0)
    detections_b = detect_point_sources(load_image(str(path_b), band="L"), observation_id="OBS-COLLIDE", band="L", threshold_sigma=4.0)

    ids_a = {d.detection_id for d in detections_a}
    ids_b = {d.detection_id for d in detections_b}
    assert ids_a & ids_b, "esta prueba documenta la colisión real sin image_index -- si deja de colisionar, revisar detect_point_sources"


def test_detect_point_sources_image_index_makes_ids_unique_across_the_observation(tmp_path):
    positions = [(30, 30), (70, 45)]
    field_a = _synthetic_star_field((128, 128), positions, seed=1)
    field_b = _synthetic_star_field((128, 128), positions, seed=2)
    path_a, path_b = tmp_path / "epoch_a.fits", tmp_path / "epoch_b.fits"
    _write_minimal_fits_2d(path_a, field_a, pixel_scale_arcsec=1.0)
    _write_minimal_fits_2d(path_b, field_b, pixel_scale_arcsec=1.0)

    detections_a = detect_point_sources(
        load_image(str(path_a), band="L"), observation_id="OBS-UNIQUE", band="L", threshold_sigma=4.0, image_index=0,
    )
    detections_b = detect_point_sources(
        load_image(str(path_b), band="L"), observation_id="OBS-UNIQUE", band="L", threshold_sigma=4.0, image_index=1,
    )

    ids_a = {d.detection_id for d in detections_a}
    ids_b = {d.detection_id for d in detections_b}
    assert not (ids_a & ids_b)
    for detection_id in ids_a | ids_b:
        assert "OBS-UNIQUE" in detection_id


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


def test_detect_point_sources_in_array_finds_injected_stars_sorted_by_brightness():
    positions = [(30, 30), (70, 45), (50, 80)]
    amplitudes = [900.0, 2500.0, 500.0]  # deliberadamente desordenadas en brillo
    yy, xx = np.mgrid[0:128, 0:128]
    field = np.full((128, 128), 100.0, dtype=np.float64)
    for (x, y), amp in zip(positions, amplitudes):
        field += amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * 1.8**2))
    rng = np.random.default_rng(7)
    field += rng.normal(0, 2.0, field.shape)

    sources = detect_point_sources_in_array(field, threshold_sigma=4.0)

    assert len(sources) >= len(positions)
    found_positions = {(round(x), round(y)) for x, y, _flux in sources}
    for x, y in positions:
        assert any(abs(fx - x) <= 1 and abs(fy - y) <= 1 for fx, fy in found_positions)

    # ordenado de más a menos brillante -- la fuente más brillante inyectada (70, 45) debe ir primero
    brightest_x, brightest_y, _ = sources[0]
    assert abs(brightest_x - 70) <= 1 and abs(brightest_y - 45) <= 1
    fluxes = [flux for _, _, flux in sources]
    assert all(earlier >= later for earlier, later in zip(fluxes, fluxes[1:]))


def test_detect_point_sources_in_array_returns_empty_for_flat_field():
    field = np.full((64, 64), 100.0)
    sources = detect_point_sources_in_array(field, threshold_sigma=5.0)
    assert sources == []
