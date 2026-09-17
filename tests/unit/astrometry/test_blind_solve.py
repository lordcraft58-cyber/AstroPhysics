"""Verificación real del resolutor de placa CIEGO (`astrometry/
blind_solve.py`): SIN ningún puntero aproximado, ni de header ni de
nombre de objeto -- solo un catálogo de referencia (más amplio que el
campo de la imagen, como sería una caché local ya descargada) y las
estrellas detectadas en píxeles reales."""
from __future__ import annotations

import math

import numpy as np
import pytest

import astrophysics_suite.astrometry.plate_solve as plate_solve_module
from astrophysics_suite.astrometry.blind_solve import (
    _quad_code_and_order,
    build_image_quads,
    build_reference_quads,
    solve_plate_blind,
)
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject, gnomonic_project


def _radius_filtered_gaia_mock(gaia_rows):
    """Mismo mock realista que test_plate_solve.py: filtra por radio
    alrededor del centro de consulta, como haría Gaia de verdad."""

    def query(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra_deg, dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    return query


def _wide_catalog_and_image(
    *, ra0=83.633, dec0=-5.391, scale_arcsec_px=1.2, rotation_deg=37.0, shape=(512, 512),
    catalog_half_extent_deg=0.3, n_catalog_stars=400, seed=42,
):
    """Catálogo de referencia disperso en un campo AMPLIO (varias veces
    el campo de la imagen, como una descarga real de caché local) y una
    imagen sintética con solo las estrellas de ese catálogo que caen
    dentro del campo de la "cámara" -- el resolutor ciego nunca recibe
    `ra0`/`dec0`/`rotation_deg`, tiene que encontrarlos."""
    rng = np.random.default_rng(seed)
    xi = rng.uniform(-catalog_half_extent_deg, catalog_half_extent_deg, n_catalog_stars)
    eta = rng.uniform(-catalog_half_extent_deg, catalog_half_extent_deg, n_catalog_stars)
    cat_ra, cat_dec = gnomonic_deproject(xi, eta, ra0, dec0)
    mags = rng.uniform(10.0, 16.0, n_catalog_stars)
    catalog_rows = [
        {"source_id": f"CAT-{i}", "ra_deg": float(r), "dec_deg": float(d), "mag_g": float(m)}
        for i, (r, d, m) in enumerate(zip(cat_ra, cat_dec, mags))
    ]

    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    scale_deg = scale_arcsec_px / 3600.0
    cd = scale_deg * np.array([[cos_t, -sin_t], [sin_t, cos_t]])
    cd_inv = np.linalg.inv(cd)

    img_xi, img_eta = gnomonic_project(np.array(cat_ra), np.array(cat_dec), ra0, dec0)
    offsets = cd_inv @ np.vstack([img_xi, img_eta])
    height, width = shape
    px = offsets[0] + width / 2.0
    py = offsets[1] + height / 2.0
    margin = 12.0
    in_field = (px >= margin) & (px < width - margin) & (py >= margin) & (py < height - margin)

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    sigma = 1.8
    for x0, y0, mag in zip(px[in_field], py[in_field], mags[in_field]):
        amplitude = 20000.0 * 10 ** (-0.4 * (mag - 10.0))
        data += amplitude * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data += rng.normal(0, 3.0, shape)

    truth = {"ra0": ra0, "dec0": dec0, "rotation_deg": rotation_deg % 360.0, "scale_arcsec_px": scale_arcsec_px, "n_in_field": int(in_field.sum())}
    return data.astype(np.float32), catalog_rows, truth


# --- Propiedades del código invariante de 4 puntos --------------------


def test_quad_code_is_invariant_to_rotation_scale_and_translation():
    rng = np.random.default_rng(1)
    points = rng.uniform(-10, 10, (4, 2))
    base = _quad_code_and_order(points)
    assert base is not None
    code, _ = base

    theta = math.radians(53.0)
    rot = np.array([[math.cos(theta), -math.sin(theta)], [math.sin(theta), math.cos(theta)]])
    transformed = (points @ rot.T) * 3.7 + np.array([100.0, -50.0])
    transformed_result = _quad_code_and_order(transformed)
    assert transformed_result is not None
    transformed_code, _ = transformed_result

    assert np.allclose(code, transformed_code, atol=1e-9)


def test_quad_code_is_the_same_regardless_of_input_order():
    rng = np.random.default_rng(2)
    points = rng.uniform(-10, 10, (4, 2))
    base = _quad_code_and_order(points)
    assert base is not None
    code, _ = base

    shuffled_result = _quad_code_and_order(points[[2, 0, 3, 1]])
    assert shuffled_result is not None
    shuffled_code, _ = shuffled_result

    assert np.allclose(code, shuffled_code, atol=1e-9)


def test_quad_code_order_maps_back_to_the_same_physical_points():
    rng = np.random.default_rng(3)
    points = rng.uniform(-10, 10, (4, 2))
    result = _quad_code_and_order(points)
    assert result is not None
    _, order = result
    assert sorted(order) == [0, 1, 2, 3]


def test_quad_code_is_none_for_degenerate_points():
    coincident = np.array([[1.0, 1.0], [1.0, 1.0], [1.0, 1.0], [1.0, 1.0]])
    assert _quad_code_and_order(coincident) is None


# --- Construcción de índices de asterismos -----------------------------


def test_build_reference_quads_needs_a_minimum_population():
    few_rows = [{"ra_deg": 10.0 + i * 0.01, "dec_deg": 41.0, "mag_g": 14.0} for i in range(2)]
    assert build_reference_quads(few_rows, k_neighbors=3) == []


def test_build_image_quads_needs_a_minimum_population():
    few = np.array([[10.0, 10.0], [20.0, 20.0]])
    assert build_image_quads(few, k_neighbors=3) == []


def test_reference_and_image_quads_share_codes_for_the_same_real_asterism():
    """El corazón del emparejamiento: 4 estrellas reales, proyectadas a
    píxel con un WCS conocido, deben producir el MISMO código desde el
    lado del catálogo (posiciones celestes) y desde el lado de la imagen
    (posiciones de píxel) -- sin esto no hay nada que emparejar."""
    ra0, dec0 = 100.0, 30.0
    ra = np.array([100.001, 100.003, 99.998, 100.002])
    dec = np.array([30.001, 29.998, 30.002, 29.999])
    scale_deg = 1.0 / 3600.0
    cd = scale_deg * np.eye(2)
    xi, eta = gnomonic_project(ra, dec, ra0, dec0)
    offsets = np.linalg.solve(cd, np.vstack([xi, eta]))
    pixel_xy = offsets.T + np.array([100.0, 100.0])

    catalog_rows = [{"ra_deg": float(r), "dec_deg": float(d), "mag_g": 14.0} for r, d in zip(ra, dec)]
    reference_quads = build_reference_quads(catalog_rows, k_neighbors=3, max_stars=10)
    image_quads = build_image_quads(pixel_xy, k_neighbors=3, max_stars=10)

    assert len(reference_quads) == 4  # un asterismo "centrado" por estrella
    assert len(image_quads) == 4
    # Cada asterismo de imagen debe tener una contraparte de catálogo muy cercana en código.
    for image_quad in image_quads:
        distances = [math.dist(image_quad.code, ref.code) for ref in reference_quads]
        assert min(distances) < 1e-3, distances


# --- solve_plate_blind de extremo a extremo -----------------------------


def test_solve_plate_blind_fails_explicitly_without_any_reference_catalog():
    data = np.full((100, 100), 200.0, dtype=np.float32)
    result = solve_plate_blind(data, header={}, catalog_rows=[])
    assert not result.success
    assert "sin catálogo de referencia local" in result.reason


def test_solve_plate_blind_fails_with_too_few_detected_stars():
    data = np.full((100, 100), 200.0, dtype=np.float32)  # campo vacío, sin fuentes
    catalog_rows = [{"ra_deg": 10.0 + i * 0.01, "dec_deg": 41.0, "mag_g": 14.0} for i in range(20)]
    result = solve_plate_blind(data, header={}, catalog_rows=catalog_rows)
    assert not result.success
    assert "estrellas detectadas" in result.reason


def test_solve_plate_blind_recovers_true_wcs_from_a_wide_reference_catalog(monkeypatch):
    data, catalog_rows, truth = _wide_catalog_and_image()
    assert truth["n_in_field"] >= 15, "la propia prueba necesita suficientes estrellas reales en el campo"
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(catalog_rows))

    result = solve_plate_blind(
        data, header={},  # SIN RA/Dec, SIN nombre de objeto -- ciego de verdad
        catalog_rows=catalog_rows, threshold_sigma=6.0, min_matched_stars=6,
    )

    assert result.success, result.reason
    assert result.n_matched >= 6
    sep_arcsec = angular_separation_deg(truth["ra0"], truth["dec0"], *result.solution.crval_deg) * 3600.0
    assert sep_arcsec < 5.0, f"separación real: {sep_arcsec:.2f}\""
    assert result.solution.rms_residual_arcsec < 1.0
    assert result.rotation_deg == pytest.approx(truth["rotation_deg"], abs=2.0)


def test_solve_plate_blind_does_not_false_positive_on_an_unrelated_catalog(monkeypatch):
    """La comprobación que de verdad importa contra un falso positivo:
    con un catálogo de una zona del cielo TOTALMENTE distinta (sin
    ningún solapamiento real con el campo de la imagen), el resolutor
    ciego no debe inventar una solución -- debe fallar honestamente."""
    data, _real_catalog, truth = _wide_catalog_and_image()
    unrelated_catalog = [
        {"source_id": f"WRONG-{i}", "ra_deg": 300.0 + (i % 20) * 0.01, "dec_deg": 60.0 + (i // 20) * 0.01, "mag_g": 13.0}
        for i in range(250)
    ]
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(unrelated_catalog))

    result = solve_plate_blind(data, header={}, catalog_rows=unrelated_catalog, threshold_sigma=6.0, min_matched_stars=6)

    assert not result.success, (
        f"un catálogo sin relación real con la imagen NUNCA debe producir una solución -- "
        f"crval devuelto: {result.solution.crval_deg if result.solution else None}"
    )
