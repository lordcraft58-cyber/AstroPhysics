"""`line_catalog.py`: catálogos públicos reales + emparejamiento
sugerido, nunca aplicado automáticamente sin confirmación (§9/§10/§20)."""
from __future__ import annotations

import pytest

from astrophysics_suite.spectroscopy.air_vacuum import air_to_vacuum
from astrophysics_suite.spectroscopy.line_catalog import (
    ARGON_ARC_LINES,
    BALMER_LINES,
    CALCIUM_LINES,
    HELIUM_ARC_LINES,
    HENEAR_ARC_LINES,
    NAMED_OBJECT_LINE_CATALOGS,
    NEBULAR_EMISSION_LINES,
    NEON_ARC_LINES,
    SODIUM_LINES,
    STELLAR_NEBULAR_LINES,
    LineType,
    arc_catalog,
    identify_object_lines,
    match_lines_to_catalog,
    nearby_catalog_lines,
)


def test_arc_catalogs_are_real_and_sorted_and_nonempty():
    for catalog in (NEON_ARC_LINES, ARGON_ARC_LINES, HELIUM_ARC_LINES):
        assert len(catalog) > 5
        wavelengths = [line.wavelength_air_angstrom for line in catalog]
        assert wavelengths == sorted(wavelengths)
        assert all(line.line_type is LineType.ARC_CALIBRATION for line in catalog)
        assert all(2000.0 < w < 12000.0 for w in wavelengths)  # rango óptico/NIR real


def test_heneaar_is_the_real_union_of_the_three_lamps():
    assert len(HENEAR_ARC_LINES) == len(NEON_ARC_LINES) + len(ARGON_ARC_LINES) + len(HELIUM_ARC_LINES)
    wavelengths = [line.wavelength_air_angstrom for line in HENEAR_ARC_LINES]
    assert wavelengths == sorted(wavelengths)


def test_arc_catalog_looks_up_by_name():
    assert arc_catalog("Ne") is NEON_ARC_LINES
    assert arc_catalog("HeNeAr") is HENEAR_ARC_LINES


def test_arc_catalog_refuses_an_unknown_lamp_instead_of_inventing_one():
    with pytest.raises(ValueError, match="ThAr"):
        arc_catalog("ThAr")


def test_stellar_lines_match_the_exact_values_from_the_spec():
    labels = {line.label: line.wavelength_air_angstrom for line in STELLAR_NEBULAR_LINES}
    assert labels["H-alpha"] == pytest.approx(6562.8)
    assert labels["H-beta"] == pytest.approx(4861.3)
    assert labels["Ca II K"] == pytest.approx(3933.7)
    assert labels["Na D2"] == pytest.approx(5889.95)


def test_identify_object_lines_filters_by_type_not_by_guessing():
    emission_only = identify_object_lines(line_type=LineType.EMISSION)
    assert all(line.line_type is LineType.EMISSION for line in emission_only)
    assert any(line.label == "H-alpha" for line in emission_only)
    assert not any(line.label == "Ca II K" for line in emission_only)  # Ca II K es absorcion por defecto


def test_match_lines_to_catalog_finds_the_real_injected_correspondence():
    # tres lineas de Ne reales, colocadas en su pixel exacto bajo una
    # dispersion conocida
    dispersion, zero_point = 1.4, 5700.0
    lines = NEON_ARC_LINES[:3]
    pixels = [(line.wavelength_air_angstrom - zero_point) / dispersion for line in lines]

    matches = match_lines_to_catalog(
        pixels, NEON_ARC_LINES, approx_dispersion_angstrom_per_px=dispersion,
        approx_wavelength_at_pixel0=zero_point, tolerance_angstrom=3.0,
    )
    assert len(matches) == 3
    for match, expected_line in zip(matches, lines):
        assert match is not None
        assert match.catalog_line is expected_line
        assert match.confidence == pytest.approx(1.0, abs=1e-6)  # coincidencia exacta


def test_match_lines_to_catalog_returns_none_for_a_pixel_with_no_real_match():
    matches = match_lines_to_catalog(
        [999999.0], NEON_ARC_LINES, approx_dispersion_angstrom_per_px=1.4,
        approx_wavelength_at_pixel0=5700.0, tolerance_angstrom=3.0,
    )
    assert matches == [None]


def test_match_confidence_degrades_with_distance_from_the_prediction():
    dispersion, zero_point = 1.4, 5700.0
    target_wavelength = NEON_ARC_LINES[5].wavelength_air_angstrom
    offset_px = 1.0 / dispersion  # ~1 A de desplazamiento real respecto al catalogo
    pixel = (target_wavelength - zero_point) / dispersion + offset_px

    matches = match_lines_to_catalog(
        [pixel], NEON_ARC_LINES, approx_dispersion_angstrom_per_px=dispersion,
        approx_wavelength_at_pixel0=zero_point, tolerance_angstrom=3.0,
    )
    assert matches[0] is not None
    assert 0.0 < matches[0].confidence < 1.0


def test_match_lines_to_catalog_rejects_nonpositive_tolerance():
    with pytest.raises(ValueError):
        match_lines_to_catalog([1.0], NEON_ARC_LINES, approx_dispersion_angstrom_per_px=1.0,
                                approx_wavelength_at_pixel0=5000.0, tolerance_angstrom=0.0)


def test_spectral_line_vacuum_wavelength_matches_air_to_vacuum():
    # H-alpha: mismo valor de referencia ya verificado en test_air_vacuum.py
    h_alpha = next(line for line in BALMER_LINES if line.label == "H-alpha")
    assert h_alpha.wavelength_vacuum_angstrom == pytest.approx(air_to_vacuum(h_alpha.wavelength_air_angstrom))
    assert h_alpha.wavelength_vacuum_angstrom == pytest.approx(6564.6, abs=0.05)
    assert h_alpha.wavelength_vacuum_angstrom > h_alpha.wavelength_air_angstrom


def test_spectral_line_vacuum_wavelength_is_a_real_number_for_every_catalog_line():
    for line in HENEAR_ARC_LINES + STELLAR_NEBULAR_LINES:
        assert line.wavelength_vacuum_angstrom > line.wavelength_air_angstrom


def test_named_object_line_catalogs_matches_the_five_real_catalogs():
    assert set(NAMED_OBJECT_LINE_CATALOGS) == {
        "Balmer (H, estelar)", "Ca II H&K (estelar)", "Na D (estelar/interestelar)",
        "Nebulares ([O III]/[N II]/[S II])", "Todas (estelar + nebular)",
    }
    assert NAMED_OBJECT_LINE_CATALOGS["Balmer (H, estelar)"] is BALMER_LINES
    assert NAMED_OBJECT_LINE_CATALOGS["Ca II H&K (estelar)"] is CALCIUM_LINES
    assert NAMED_OBJECT_LINE_CATALOGS["Na D (estelar/interestelar)"] is SODIUM_LINES
    assert NAMED_OBJECT_LINE_CATALOGS["Nebulares ([O III]/[N II]/[S II])"] is NEBULAR_EMISSION_LINES
    assert NAMED_OBJECT_LINE_CATALOGS["Todas (estelar + nebular)"] is STELLAR_NEBULAR_LINES


def test_nearby_catalog_lines_finds_and_sorts_real_candidates_by_distance():
    h_alpha = next(line for line in BALMER_LINES if line.label == "H-alpha")
    h_beta = next(line for line in BALMER_LINES if line.label == "H-beta")
    # 6562.8 (Ha) y 4861.3 (Hb) estan a mas de 1700 A -- una tolerancia de 20 A solo alcanza a una de las dos
    candidates = nearby_catalog_lines(h_alpha.wavelength_air_angstrom + 3.0, BALMER_LINES, tolerance_angstrom=20.0)
    assert candidates == (h_alpha,)
    assert h_beta not in candidates


def test_nearby_catalog_lines_orders_multiple_real_candidates_by_closeness():
    # Ca II K y H (3933.7 / 3968.5) estan a menos de 35 A -- con tolerancia amplia deben salir las dos, la mas cercana primero
    target = 3950.0  # mas cerca de Ca II K (3933.7, Delta=16.3) que de Ca II H (3968.5, Delta=18.5)
    candidates = nearby_catalog_lines(target, CALCIUM_LINES, tolerance_angstrom=25.0)
    assert [line.label for line in candidates] == ["Ca II K", "Ca II H"]


def test_nearby_catalog_lines_returns_nothing_when_no_real_line_is_close():
    candidates = nearby_catalog_lines(9999.0, BALMER_LINES, tolerance_angstrom=5.0)
    assert candidates == ()


def test_nearby_catalog_lines_rejects_nonpositive_tolerance():
    with pytest.raises(ValueError):
        nearby_catalog_lines(5000.0, BALMER_LINES, tolerance_angstrom=0.0)
