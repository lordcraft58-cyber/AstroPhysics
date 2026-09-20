"""`line_catalog.py`: catálogos públicos reales + emparejamiento
sugerido, nunca aplicado automáticamente sin confirmación (§9/§10/§20)."""
from __future__ import annotations

import pytest

from astrophysics_suite.spectroscopy.line_catalog import (
    ARGON_ARC_LINES,
    HELIUM_ARC_LINES,
    HENEAR_ARC_LINES,
    NEON_ARC_LINES,
    STELLAR_NEBULAR_LINES,
    LineType,
    arc_catalog,
    identify_object_lines,
    match_lines_to_catalog,
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
