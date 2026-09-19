"""Pruebas reales del WCS construido desde la óptica: la orientación del
cielo (norte arriba, este a la IZQUIERDA salvo espejo), la escala
recuperada y la rotación se comprueban contra geometría conocida -- una
convención de paridad equivocada aquí corrompería en silencio toda la
identificación de catálogo, así que se verifica explícitamente."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.astrometry.optical_wcs import build_wcs_from_optics, is_optical_wcs, pixel_scale_of
from astrophysics_suite.astrometry.wcs_fit import angular_separation_deg

_CENTER_RA, _CENTER_DEC = 10.684708, 41.268750  # M 31 real
_SHAPE = (3008, 3008)  # ASI533MC Pro
_SCALE = 0.7756  # "/px a 1000 mm


def _solution(**overrides):
    params = dict(
        center_ra_deg=_CENTER_RA, center_dec_deg=_CENTER_DEC, pixel_scale_arcsec=_SCALE, image_shape=_SHAPE
    )
    params.update(overrides)
    return build_wcs_from_optics(**params)


def test_reference_pixel_maps_exactly_to_the_declared_center():
    solution = _solution()
    ra, dec = solution.pixel_to_sky(*solution.crpix_px)
    assert ra == pytest.approx(_CENTER_RA, abs=1e-9)
    assert dec == pytest.approx(_CENTER_DEC, abs=1e-9)


def test_reference_pixel_is_the_geometric_center_like_plate_solve_uses():
    solution = _solution()
    assert solution.crpix_px == (_SHAPE[1] / 2.0, _SHAPE[0] / 2.0)


def test_recovered_pixel_scale_matches_the_declared_optics():
    solution = _solution()
    assert pixel_scale_of(solution) == pytest.approx(_SCALE, rel=1e-9)


def test_north_is_up_and_east_is_left_without_mirror():
    solution = _solution()
    cx, cy = solution.crpix_px

    # +1 px hacia la DERECHA debe BAJAR la RA (el este queda a la izquierda)
    ra_right, _ = solution.pixel_to_sky(cx + 1.0, cy)
    assert ra_right < _CENTER_RA

    # +1 px hacia ARRIBA en índice de fila (y creciente) sube la Dec
    _, dec_up = solution.pixel_to_sky(cx, cy + 1.0)
    assert dec_up > _CENTER_DEC


def test_mirrored_image_puts_east_on_the_right():
    normal = _solution()
    mirrored = _solution(mirrored=True)
    cx, cy = normal.crpix_px

    ra_normal, _ = normal.pixel_to_sky(cx + 1.0, cy)
    ra_mirror, _ = mirrored.pixel_to_sky(cx + 1.0, cy)
    assert ra_normal < _CENTER_RA < ra_mirror

    # la escala es la misma: un espejo no cambia cuánto cubre un píxel
    assert pixel_scale_of(mirrored) == pytest.approx(pixel_scale_of(normal), rel=1e-12)
    # ...pero sí la PARIDAD del campo, que es el signo del determinante:
    # negativo para una imagen normal del cielo (convención estándar, RA
    # creciendo hacia la izquierda), positivo cuando está reflejada.
    assert np.linalg.det(normal.cd_matrix_deg_per_px) < 0
    assert np.linalg.det(mirrored.cd_matrix_deg_per_px) > 0


def test_one_pixel_step_covers_exactly_the_declared_scale_on_the_sky():
    solution = _solution()
    cx, cy = solution.crpix_px
    ra0, dec0 = solution.pixel_to_sky(cx, cy)
    ra1, dec1 = solution.pixel_to_sky(cx + 1.0, cy)
    separation_arcsec = angular_separation_deg(ra0, dec0, ra1, dec1) * 3600.0
    assert separation_arcsec == pytest.approx(_SCALE, rel=1e-6)


def test_rotation_turns_the_field_by_the_declared_angle():
    straight = _solution()
    rotated = _solution(rotation_deg=90.0)
    cx, cy = straight.crpix_px

    # sin rotación, +1 px en y sube la Dec; con 90° esa misma dirección
    # deja de mover la Dec (pasa a moverse en RA)
    _, dec_straight = straight.pixel_to_sky(cx, cy + 1.0)
    _, dec_rotated = rotated.pixel_to_sky(cx, cy + 1.0)
    assert dec_straight - _CENTER_DEC == pytest.approx(_SCALE / 3600.0, rel=1e-4)
    assert abs(dec_rotated - _CENTER_DEC) < 1e-9

    # la escala se conserva bajo rotación
    assert pixel_scale_of(rotated) == pytest.approx(_SCALE, rel=1e-9)


def test_full_field_span_matches_the_camera_field_of_view():
    solution = _solution()
    height, width = _SHAPE
    ra_left, dec_left = solution.pixel_to_sky(0.0, height / 2.0)
    ra_right, dec_right = solution.pixel_to_sky(float(width), height / 2.0)
    span_deg = angular_separation_deg(ra_left, dec_left, ra_right, dec_right)
    assert span_deg == pytest.approx(width * _SCALE / 3600.0, rel=1e-4)
    assert span_deg == pytest.approx(0.648, abs=0.002)  # 38.9' reales


def test_sky_to_pixel_round_trips():
    solution = _solution(rotation_deg=33.0)
    for x, y in ((100.0, 200.0), (1504.0, 1504.0), (2900.0, 80.0)):
        ra, dec = solution.pixel_to_sky(x, y)
        back_x, back_y = solution.sky_to_pixel(ra, dec)
        assert back_x == pytest.approx(x, abs=1e-6)
        assert back_y == pytest.approx(y, abs=1e-6)


def test_optical_solution_is_flagged_as_declared_not_fitted():
    solution = _solution()
    assert is_optical_wcs(solution) is True
    assert solution.n_stars == 0
    assert solution.residuals_arcsec == ()


def test_rejects_physically_impossible_inputs():
    with pytest.raises(ValueError):
        _solution(center_dec_deg=120.0)
    with pytest.raises(ValueError):
        _solution(pixel_scale_arcsec=0.0)
    with pytest.raises(ValueError):
        _solution(image_shape=(0, 100))
    with pytest.raises(ValueError):
        _solution(center_ra_deg=math.nan)
