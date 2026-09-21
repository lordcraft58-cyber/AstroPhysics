"""`telluric_lines.py`: bandas telúricas conocidas -- solo identifica
solape, nunca corrige nada (§46)."""
from __future__ import annotations

import pytest

from astrophysics_suite.spectroscopy.telluric_lines import (
    TELLURIC_BANDS,
    bands_overlapping_range,
    find_telluric_overlap,
)


def test_catalog_is_modest_and_sorted_by_wavelength():
    assert 3 <= len(TELLURIC_BANDS) <= 15
    starts = [b.wavelength_start_angstrom for b in TELLURIC_BANDS]
    assert starts == sorted(starts)


def test_catalog_bands_never_carry_an_invented_numeric_depth():
    for band in TELLURIC_BANDS:
        assert not hasattr(band, "depth")
        assert not hasattr(band, "equivalent_width")
        assert band.strength in ("strong", "moderate")


def test_find_telluric_overlap_matches_a_real_band():
    band = find_telluric_overlap(6870.0)
    assert band is not None
    assert band.name == "O2 B"
    assert band.species == "O2"


def test_find_telluric_overlap_returns_none_outside_any_band():
    assert find_telluric_overlap(6562.8) is None  # H-alpha, muy lejos de cualquier banda telúrica del catálogo


def test_find_telluric_overlap_is_inclusive_at_the_boundaries():
    band = find_telluric_overlap(6867.0)
    assert band is not None and band.name == "O2 B"
    band = find_telluric_overlap(6884.0)
    assert band is not None and band.name == "O2 B"


def test_bands_overlapping_range_finds_all_bands_in_a_wide_range():
    bands = bands_overlapping_range(6800.0, 7700.0)
    names = {b.name for b in bands}
    assert "O2 B" in names
    assert "O2 A" in names


def test_bands_overlapping_range_empty_for_a_clean_range():
    assert bands_overlapping_range(4000.0, 4500.0) == ()


def test_bands_overlapping_range_rejects_a_reversed_range():
    with pytest.raises(ValueError):
        bands_overlapping_range(7000.0, 6000.0)
