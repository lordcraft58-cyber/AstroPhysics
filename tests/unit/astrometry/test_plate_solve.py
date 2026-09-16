"""Verificación real del motor de plate solving automático:
`solve_plate` se prueba contra un campo sintético con una solución WCS
verdadera conocida (rotación + escala + posible espejo), estrellas
Gaia simuladas (mockeadas en el punto real de consulta,
`astrophysics_suite.astrometry.plate_solve.query_gaia_neighbors`) e
imágenes con fuentes puntuales reales inyectadas en sus posiciones de
píxel verdaderas -- nunca comprobando solo "no lanza"."""
from __future__ import annotations

import math

import numpy as np
import pytest

import astrophysics_suite.astrometry.plate_solve as plate_solve_module
from astrophysics_suite.astrometry.plate_solve import (
    estimate_approx_pointing_from_header,
    estimate_approx_scale_from_header,
    solve_plate,
)
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg, gnomonic_deproject


def _radius_filtered_gaia_mock(gaia_rows):
    """Mock realista de `query_gaia_neighbors`: a diferencia de devolver
    la lista completa sin más, filtra por radio alrededor del centro de
    consulta -- igual que haría una consulta real a Gaia -- para que un
    puntero aproximado muy alejado del campo real no "vea" estrellas que
    de verdad no estarían en ese radio."""

    def query(ra_deg, dec_deg, *, radius_arcsec=3.0, mag_limit=20.0, max_rows=25):
        return [row for row in gaia_rows if angular_separation_deg(ra_deg, dec_deg, row["ra_deg"], row["dec_deg"]) * 3600.0 <= radius_arcsec][:max_rows]

    return query


def _true_cd(scale_arcsec_px: float, rotation_deg: float, mirrored: bool) -> np.ndarray:
    scale_deg = scale_arcsec_px / 3600.0
    theta = math.radians(rotation_deg)
    cos_t, sin_t = math.cos(theta), math.sin(theta)
    rotation = np.array([[cos_t, -sin_t], [sin_t, cos_t]])
    parity = -1 if mirrored else 1
    return scale_deg * np.array([[parity, 0.0], [0.0, 1.0]]) @ rotation


def _synthetic_field_and_catalog(
    shape=(200, 200), *, ra0=150.0, dec0=20.0, scale_arcsec_px=1.2, rotation_deg=23.0, mirrored=False, n_stars=25, seed=11
):
    """Genera un campo sintético real: N estrellas en posiciones de
    píxel aleatorias, sus posiciones de cielo verdaderas calculadas con
    el WCS verdadero (deproyección gnomónica real, no inventada), y una
    imagen con perfiles gaussianos reales inyectados en esas posiciones
    de píxel exactas."""
    rng = np.random.default_rng(seed)
    height, width = shape
    crpix = (width / 2.0, height / 2.0)
    cd = _true_cd(scale_arcsec_px, rotation_deg, mirrored)

    margin = 15.0
    xs = rng.uniform(margin, width - margin, n_stars)
    ys = rng.uniform(margin, height - margin, n_stars)
    dx, dy = xs - crpix[0], ys - crpix[1]
    offsets = cd @ np.vstack([dx, dy])
    ra, dec = gnomonic_deproject(offsets[0], offsets[1], ra0, dec0)

    data = np.full(shape, 200.0, dtype=np.float64)
    yy, xx = np.mgrid[0:height, 0:width]
    fluxes = rng.uniform(15000.0, 40000.0, n_stars)
    sigma = 1.8
    for x0, y0, flux in zip(xs, ys, fluxes):
        data += flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    data += rng.normal(0, 3.0, shape)

    gaia_rows = [
        {"ra_deg": float(r), "dec_deg": float(d), "source_id": f"GAIA-{i}", "mag_g": 14.0}
        for i, (r, d) in enumerate(zip(ra, dec))
    ]
    return data, gaia_rows, {"crpix": crpix, "cd": cd, "ra0": ra0, "dec0": dec0}


def test_solve_plate_recovers_true_wcs_with_approximate_pointing_and_scale(monkeypatch):
    data, gaia_rows, truth = _synthetic_field_and_catalog(rotation_deg=23.0, scale_arcsec_px=1.2)
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))

    # puntero y escala deliberadamente APROXIMADOS, no exactos -- así es como
    # llegarían de verdad desde un header FITS o de lo que el usuario escriba.
    result = solve_plate(
        data,
        header={},
        approx_ra_deg=truth["ra0"] + 0.02,
        approx_dec_deg=truth["dec0"] - 0.015,
        approx_scale_arcsec_px=1.2 * 1.03,
        rotation_step_deg=5.0,
        threshold_sigma=6.0,
    )

    assert result.success, result.reason
    assert result.n_matched >= 6
    assert result.solution.rms_residual_arcsec < 1.0

    true_ra, true_dec = gnomonic_deproject(np.array([0.0]), np.array([0.0]), truth["ra0"], truth["dec0"])
    solved_ra, solved_dec = result.solution.pixel_to_sky(*truth["crpix"])
    # separación angular real entre el centro verdadero y el resuelto
    sep_arcsec = angular_separation_deg(float(true_ra[0]), float(true_dec[0]), solved_ra, solved_dec) * 3600.0
    assert sep_arcsec < 3.0

    assert result.rotation_deg == pytest.approx(23.0, abs=1.0)
    assert result.mirrored is False


def test_solve_plate_recovers_mirrored_orientation(monkeypatch):
    data, gaia_rows, truth = _synthetic_field_and_catalog(rotation_deg=110.0, scale_arcsec_px=0.9, mirrored=True)
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))

    result = solve_plate(
        data,
        header={},
        approx_ra_deg=truth["ra0"] - 0.01,
        approx_dec_deg=truth["dec0"] + 0.01,
        approx_scale_arcsec_px=0.9 * 0.97,
        rotation_step_deg=5.0,
        threshold_sigma=6.0,
    )

    assert result.success, result.reason
    assert result.mirrored is True
    assert result.rotation_deg == pytest.approx(110.0, abs=1.0)


def test_solve_plate_fails_honestly_without_approximate_pointing():
    data = np.full((100, 100), 200.0)
    result = solve_plate(data, header={}, approx_scale_arcsec_px=1.0)
    assert result.success is False
    assert result.solution is None
    assert "posición aproximada" in result.reason


def test_solve_plate_fails_honestly_without_approximate_scale():
    data = np.full((100, 100), 200.0)
    result = solve_plate(data, header={}, approx_ra_deg=150.0, approx_dec_deg=20.0)
    assert result.success is False
    assert result.solution is None
    assert "escala aproximada" in result.reason


def test_solve_plate_fails_honestly_with_too_few_detected_stars():
    data = np.full((100, 100), 200.0)  # campo plano, sin estrellas
    result = solve_plate(data, header={}, approx_ra_deg=150.0, approx_dec_deg=20.0, approx_scale_arcsec_px=1.0)
    assert result.success is False
    assert result.solution is None
    assert "estrellas detectadas" in result.reason


def test_solve_plate_fails_honestly_when_gaia_has_no_nearby_sources(monkeypatch):
    data, _gaia_rows, truth = _synthetic_field_and_catalog()
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", lambda *a, **k: [])

    result = solve_plate(data, header={}, approx_ra_deg=truth["ra0"], approx_dec_deg=truth["dec0"], approx_scale_arcsec_px=1.2, threshold_sigma=6.0)

    assert result.success is False
    assert result.solution is None
    assert "Gaia" in result.reason


def test_solve_plate_rejects_when_approximate_pointing_is_far_off(monkeypatch):
    data, gaia_rows, truth = _synthetic_field_and_catalog()
    monkeypatch.setattr(plate_solve_module, "query_gaia_neighbors", _radius_filtered_gaia_mock(gaia_rows))

    # puntero deliberadamente muy alejado del real -- ningún catálogo real
    # coincidirá con el campo detectado, no debe inventar una solución.
    result = solve_plate(
        data, header={}, approx_ra_deg=truth["ra0"] + 5.0, approx_dec_deg=truth["dec0"], approx_scale_arcsec_px=1.2, rotation_step_deg=10.0, threshold_sigma=6.0
    )

    assert result.success is False
    assert result.solution is None


def test_estimate_approx_pointing_from_header_parses_sexagesimal_objctra():
    header = {"OBJCTRA": "10 00 00", "OBJCTDEC": "+20 00 00"}
    pointing = estimate_approx_pointing_from_header(header)
    assert pointing is not None
    ra_deg, dec_deg = pointing
    assert ra_deg == pytest.approx(150.0, abs=0.01)
    assert dec_deg == pytest.approx(20.0, abs=0.01)


def test_estimate_approx_pointing_from_header_parses_decimal_ra_dec():
    header = {"RA": 150.25, "DEC": -20.5}
    pointing = estimate_approx_pointing_from_header(header)
    assert pointing == pytest.approx((150.25, -20.5))


def test_estimate_approx_pointing_from_header_returns_none_without_coordinates():
    assert estimate_approx_pointing_from_header({}) is None
    assert estimate_approx_pointing_from_header({"OBJECT": "M31"}) is None


def test_estimate_approx_scale_from_header_uses_pixscale_directly():
    assert estimate_approx_scale_from_header({"PIXSCALE": 1.5}) == pytest.approx(1.5)


def test_estimate_approx_scale_from_header_derives_from_focal_length_and_pixel_size():
    # 3.75 um de pixel, 900 mm de focal -> 206265 * (3.75/1000) / 900 ~= 0.8594"/px
    scale = estimate_approx_scale_from_header({"FOCALLEN": 900.0, "XPIXSZ": 3.75})
    assert scale == pytest.approx(206265.0 * 0.00375 / 900.0, rel=1e-6)


def test_estimate_approx_scale_from_header_returns_none_without_enough_info():
    assert estimate_approx_scale_from_header({}) is None
    assert estimate_approx_scale_from_header({"FOCALLEN": 900.0}) is None
