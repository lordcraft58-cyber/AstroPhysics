"""Pruebas de la lectura de óptica desde cabeceras reales -- incluida la
cabecera literal de los lights de M 31 del usuario (ZWO ASI533MC Pro a
749 mm), que es la referencia real de este motor."""
from __future__ import annotations

import pytest

from astrophysics_suite.instruments.cameras import ZWO_ASI533MC_PRO
from astrophysics_suite.instruments.header import optical_setup_from_header, read_header_optics

# Cabecera real (subconjunto literal) de Light_M31_300s_0001.fit
_REAL_M31_HEADER = {
    "NAXIS1": 3008,
    "NAXIS2": 3008,
    "XPIXSZ": 3.75999999046326,
    "YPIXSZ": 3.75999999046326,
    "FOCALLEN": 749,
    "INSTRUME": "ZWO ASI533MC Pro",
    "TELESCOP": "EQMod Mount",
    "RA": 11.087505,
    "DEC": 41.412641,
    "OBJECT": "M 31",
    "BAYERPAT": "RGGB",
    "XBINNING": 1,
}


def test_reads_the_real_m31_header_completely():
    optics = read_header_optics(_REAL_M31_HEADER)
    assert optics.camera_name == "ZWO ASI533MC Pro"
    assert optics.matched_camera is ZWO_ASI533MC_PRO
    assert optics.pixel_size_um == pytest.approx(3.76, abs=1e-6)
    assert optics.focal_length_mm == pytest.approx(749.0)
    assert (optics.width_px, optics.height_px) == (3008, 3008)
    assert optics.binning == 1
    assert optics.center_ra_deg == pytest.approx(11.087505)
    assert optics.center_dec_deg == pytest.approx(41.412641)
    assert optics.object_name == "M 31"


def test_catalog_agrees_with_the_users_real_camera_header():
    # si esto falla, el catálogo interno está mal para la cámara del
    # usuario -- es la comprobación que impide un WCS mal escalado.
    optics = read_header_optics(_REAL_M31_HEADER)
    assert optics.pixel_size_disagreement_um == pytest.approx(0.0, abs=1e-5)


def test_real_header_yields_the_users_actual_plate_scale_and_field():
    setup = optical_setup_from_header(_REAL_M31_HEADER)
    assert setup is not None
    assert setup.pixel_scale_arcsec == pytest.approx(1.0355, abs=0.001)
    width_deg, height_deg = setup.field_of_view_deg
    assert width_deg * 60 == pytest.approx(51.9, abs=0.1)
    assert height_deg * 60 == pytest.approx(51.9, abs=0.1)


def test_header_pixel_size_wins_over_the_internal_catalog():
    header = dict(_REAL_M31_HEADER, XPIXSZ=9.0)  # cabecera que contradice al catálogo
    setup = optical_setup_from_header(header)
    assert setup is not None
    assert setup.pixel_size_um == pytest.approx(9.0)  # manda la cabecera real

    optics = read_header_optics(header)
    assert optics.pixel_size_disagreement_um == pytest.approx(9.0 - 3.76, abs=1e-6)


def test_catalog_fills_only_what_the_header_omits():
    header = {"INSTRUME": "ZWO ASI533MC Pro", "FOCALLEN": 749}  # sin XPIXSZ ni NAXIS
    setup = optical_setup_from_header(header)
    assert setup is not None
    assert setup.pixel_size_um == pytest.approx(3.76)
    assert (setup.width_px, setup.height_px) == (3008, 3008)


def test_missing_focal_length_yields_none_instead_of_a_guess():
    header = dict(_REAL_M31_HEADER)
    del header["FOCALLEN"]
    assert optical_setup_from_header(header) is None


def test_unknown_camera_is_not_matched_to_a_similar_one():
    optics = read_header_optics({"INSTRUME": "Cámara Rara 9000", "FOCALLEN": 500, "XPIXSZ": 5.0})
    assert optics.camera_name == "Cámara Rara 9000"
    assert optics.matched_camera is None
    assert optics.pixel_size_disagreement_um is None
    # aun sin catálogo, la cabecera basta si trae píxel, focal y geometría
    assert optical_setup_from_header({"INSTRUME": "Rara", "FOCALLEN": 500, "XPIXSZ": 5.0, "NAXIS1": 100, "NAXIS2": 80}) is not None


def test_garbage_values_are_ignored_not_coerced():
    optics = read_header_optics({"XPIXSZ": "no es un número", "FOCALLEN": -5, "RA": 999.0, "DEC": "x"})
    assert optics.pixel_size_um is None
    assert optics.focal_length_mm is None  # una focal negativa no es una focal
    assert optics.center_ra_deg is None  # RA fuera de rango no se "corrige"
    assert optics.center_dec_deg is None


def test_binning_from_header_reaches_the_plate_scale():
    setup = optical_setup_from_header(dict(_REAL_M31_HEADER, XBINNING=2))
    assert setup is not None
    assert setup.binning == 2
    assert setup.pixel_scale_arcsec == pytest.approx(2 * 1.0355, abs=0.002)
