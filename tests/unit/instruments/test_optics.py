"""Pruebas reales de la óptica del equipo: la escala de placa y el campo
se comparan contra los valores que da cualquier calculadora de campo
astronómica para combinaciones conocidas (la ZWO ASI533MC Pro del
usuario sobre focales redondas), no solo contra "no lanza excepción"."""
from __future__ import annotations

import math

import pytest

from astrophysics_suite.instruments.cameras import (
    BUILTIN_CAMERAS,
    ZWO_ASI533MC_PRO,
    camera_matching_pixel_size,
    find_camera,
)
from astrophysics_suite.instruments.optics import (
    OpticalSetup,
    field_of_view_deg,
    pixel_scale_arcsec_per_px,
)


def test_asi533mc_pro_catalog_geometry_is_the_real_one():
    camera = ZWO_ASI533MC_PRO
    assert (camera.width_px, camera.height_px) == (3008, 3008)
    assert camera.pixel_size_um == pytest.approx(3.76)
    assert camera.color is True
    # sensor cuadrado de 1": 3008 * 3.76 µm = 11.31 mm de lado
    assert camera.sensor_width_mm == pytest.approx(11.31, abs=0.01)
    assert camera.sensor_height_mm == pytest.approx(11.31, abs=0.01)
    assert camera.megapixels == pytest.approx(9.05, abs=0.01)


def test_pixel_scale_matches_the_standard_field_calculator_value():
    # 206.265 * 3.76 / 1000 = 0.7756 "/px -- el valor que da cualquier
    # calculadora de campo para esta cámara a 1000 mm de focal.
    scale = pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=1000.0)
    assert scale == pytest.approx(0.7756, abs=0.0005)

    # a la mitad de focal, el doble de escala (relación exactamente lineal
    # en este régimen de ángulos pequeños)
    half = pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=500.0)
    assert half == pytest.approx(2 * scale, rel=1e-6)


def test_pixel_scale_uses_a_real_arctangent_not_the_small_angle_shortcut():
    # con una focal absurdamente corta el arcotangente y la aproximación
    # lineal SÍ difieren -- confirma que se calcula el ángulo de verdad.
    # Un "píxel" de 1 mm a 1 mm de focal subtiende arctan(1) = 45° EXACTOS
    # = 162000", no los 206265" que daría la aproximación lineal.
    linear = 206264.806 * (1000.0 / 1000.0) / 1.0
    real = pixel_scale_arcsec_per_px(pixel_size_um=1000.0, focal_length_mm=1.0)
    assert real < linear
    assert real == pytest.approx(45.0 * 3600.0, rel=1e-12)
    assert math.degrees(math.atan(1.0)) == pytest.approx(45.0, rel=1e-12)


def test_binning_doubles_the_pixel_scale_and_keeps_the_field():
    unbinned = pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=1000.0)
    binned = pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=1000.0, binning=2)
    assert binned == pytest.approx(2 * unbinned, rel=1e-6)

    fov_unbinned = field_of_view_deg(pixel_scale_arcsec=unbinned, width_px=3008, height_px=3008)
    fov_binned = field_of_view_deg(pixel_scale_arcsec=binned, width_px=3008, height_px=3008, binning=2)
    assert fov_binned[0] == pytest.approx(fov_unbinned[0], rel=1e-6)


def test_field_of_view_of_the_users_camera_at_a_known_focal_length():
    setup = OpticalSetup(
        camera_name=ZWO_ASI533MC_PRO.name, pixel_size_um=3.76, width_px=3008, height_px=3008, focal_length_mm=1000.0
    )
    width_deg, height_deg = setup.field_of_view_deg
    # 3008 px * 0.7756 "/px = 2333" = 0.648 grados = 38.9 arcmin
    assert width_deg == pytest.approx(0.648, abs=0.002)
    assert height_deg == pytest.approx(width_deg, rel=1e-9)  # sensor cuadrado
    assert width_deg * 60 == pytest.approx(38.9, abs=0.1)


def test_focal_ratio_and_dawes_limit_need_a_real_aperture():
    with_aperture = OpticalSetup(
        camera_name="x", pixel_size_um=3.76, width_px=3008, height_px=3008, focal_length_mm=800.0, aperture_mm=200.0
    )
    assert with_aperture.focal_ratio == pytest.approx(4.0)
    assert with_aperture.dawes_limit_arcsec == pytest.approx(0.58, abs=0.01)

    without = OpticalSetup(camera_name="x", pixel_size_um=3.76, width_px=3008, height_px=3008, focal_length_mm=800.0)
    assert without.focal_ratio is None  # nunca una abertura "típica" inventada
    assert without.dawes_limit_arcsec is None


def test_sampling_ratio_classifies_real_seeing():
    # 0.7756 "/px con FWHM de 3" -> 3.9 px por FWHM
    setup = OpticalSetup(
        camera_name="x", pixel_size_um=3.76, width_px=3008, height_px=3008, focal_length_mm=1000.0
    )
    assert setup.sampling_ratio(3.0) == pytest.approx(3.87, abs=0.02)
    assert "sobremuestreado" in setup.describe_sampling(3.0)

    corto = OpticalSetup(camera_name="x", pixel_size_um=3.76, width_px=3008, height_px=3008, focal_length_mm=300.0)
    assert "submuestreado" in corto.describe_sampling(3.0)
    assert corto.sampling_ratio(0.0) is None  # un FWHM no positivo no se interpreta


def test_optics_rejects_impossible_inputs():
    with pytest.raises(ValueError):
        pixel_scale_arcsec_per_px(pixel_size_um=0.0, focal_length_mm=1000.0)
    with pytest.raises(ValueError):
        pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=-1.0)
    with pytest.raises(ValueError):
        pixel_scale_arcsec_per_px(pixel_size_um=3.76, focal_length_mm=1000.0, binning=0)


def test_camera_lookup_is_exact_and_never_guesses_a_similar_one():
    assert find_camera("ZWO ASI533MC Pro") is ZWO_ASI533MC_PRO
    assert find_camera("  zwo asi533mc pro  ") is ZWO_ASI533MC_PRO
    assert find_camera("ZWO ASI533") is None  # parecida NO es la misma
    assert find_camera("cámara inexistente") is None


def test_pixel_size_suggestion_returns_all_real_matches():
    matches = camera_matching_pixel_size(3.76)
    names = {c.name for c in matches}
    assert ZWO_ASI533MC_PRO.name in names
    assert len(matches) > 1  # varias cámaras reales comparten 3.76 µm
    assert camera_matching_pixel_size(99.0) == []


def test_every_catalog_entry_has_physically_coherent_geometry():
    for camera in BUILTIN_CAMERAS:
        assert camera.width_px > 0 and camera.height_px > 0
        assert 0.5 < camera.pixel_size_um < 30.0
        assert 1.0 < camera.sensor_width_mm < 70.0  # de 1" a full frame
