"""`synthetic_photometry.py`: magnitud AB real (definición exacta) +
magnitud relativa, vía una curva de transmisión real -- nunca inventa
un punto cero ni extrapola sobre datos que el espectro no cubre (§50)."""
from __future__ import annotations

import astropy.units as u
import numpy as np
import pytest

from astrophysics_suite.spectroscopy.synthetic_photometry import (
    JOHNSON_COUSINS_FILTERS,
    SDSS_FILTERS,
    FilterCurve,
    ab_magnitude,
    load_filter_curve,
    relative_magnitude,
    synthetic_effective_f_nu,
)


def _tophat_filter(lo=5000.0, hi=6000.0, n=500, name="tophat"):
    wavelength = np.linspace(lo, hi, n)
    return FilterCurve(name, wavelength, np.ones_like(wavelength))


def _flat_f_nu_spectrum(f_nu_jy, wavelength):
    flux = (f_nu_jy * u.Jy).to(
        u.erg / u.s / u.cm**2 / u.AA, equivalencies=u.spectral_density(wavelength * u.AA)
    ).value
    return flux


def test_flat_3631_jy_spectrum_has_ab_magnitude_zero():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 3000)
    flux = _flat_f_nu_spectrum(3631.0, wavelength)

    mag = ab_magnitude(wavelength, flux, filt)
    assert mag == pytest.approx(0.0, abs=1e-3)


def test_scaling_flux_by_100_changes_magnitude_by_exactly_5():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 3000)
    flux = _flat_f_nu_spectrum(1000.0, wavelength)

    bright = ab_magnitude(wavelength, flux, filt)
    faint = ab_magnitude(wavelength, flux * 0.01, filt)
    assert faint - bright == pytest.approx(5.0, abs=1e-3)


def test_incomplete_wavelength_coverage_returns_none_not_an_extrapolated_value():
    filt = _tophat_filter(lo=5000.0, hi=6000.0)
    wavelength = np.linspace(5200.0, 5800.0, 200)  # no cubre todo el filtro
    flux = _flat_f_nu_spectrum(1000.0, wavelength)

    assert ab_magnitude(wavelength, flux, filt) is None
    assert synthetic_effective_f_nu(wavelength, flux, filt) is None


def test_full_coverage_with_margin_gives_a_real_value():
    filt = _tophat_filter(lo=5000.0, hi=6000.0)
    wavelength = np.linspace(4000.0, 7000.0, 3000)  # cubre de sobra
    flux = _flat_f_nu_spectrum(1000.0, wavelength)

    assert ab_magnitude(wavelength, flux, filt) is not None


def test_nonpositive_effective_flux_returns_none():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 3000)
    flux = np.full_like(wavelength, -1e-15)  # flujo negativo en toda la banda -- no hay magnitud real

    assert ab_magnitude(wavelength, flux, filt) is None


def test_rejects_mismatched_shapes():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 100)
    with pytest.raises(ValueError):
        ab_magnitude(wavelength, np.zeros(50), filt)


def test_rejects_a_filter_curve_with_no_positive_area():
    filt = FilterCurve("cero", np.linspace(5000.0, 6000.0, 10), np.zeros(10))
    wavelength = np.linspace(4000.0, 7000.0, 100)
    flux = np.full_like(wavelength, 1e-15)
    with pytest.raises(ValueError):
        ab_magnitude(wavelength, flux, filt)


def test_relative_magnitude_recovers_a_known_flux_ratio():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 3000)
    flux_a = _flat_f_nu_spectrum(1000.0, wavelength)
    flux_b = flux_a * 2.512  # b es ~1 magnitud mas brillante que a

    rel = relative_magnitude(wavelength, flux_a, wavelength, flux_b, filt)
    assert rel == pytest.approx(1.0, abs=1e-3)


def test_relative_magnitude_of_identical_spectra_is_zero():
    filt = _tophat_filter()
    wavelength = np.linspace(4000.0, 7000.0, 3000)
    flux = _flat_f_nu_spectrum(1000.0, wavelength)

    assert relative_magnitude(wavelength, flux, wavelength, flux, filt) == pytest.approx(0.0, abs=1e-6)


def test_relative_magnitude_returns_none_when_either_side_lacks_coverage():
    filt = _tophat_filter(lo=5000.0, hi=6000.0)
    wide_wavelength = np.linspace(4000.0, 7000.0, 3000)
    narrow_wavelength = np.linspace(5200.0, 5800.0, 100)
    flux_wide = _flat_f_nu_spectrum(1000.0, wide_wavelength)
    flux_narrow = _flat_f_nu_spectrum(1000.0, narrow_wavelength)

    assert relative_magnitude(wide_wavelength, flux_wide, narrow_wavelength, flux_narrow, filt) is None


def test_load_filter_curve_reads_a_real_two_column_file(tmp_path):
    path = tmp_path / "filter.dat"
    path.write_text("# SVO-style comment header\n5000.0 0.1\n5500.0 0.9\n6000.0 0.2\n")

    curve = load_filter_curve(str(path), name="test filter")
    assert curve.name == "test filter"
    np.testing.assert_allclose(curve.wavelength_angstrom, [5000.0, 5500.0, 6000.0])
    np.testing.assert_allclose(curve.transmission, [0.1, 0.9, 0.2])


def test_load_filter_curve_sorts_an_unsorted_file(tmp_path):
    path = tmp_path / "unsorted.dat"
    path.write_text("6000.0 0.2\n5000.0 0.1\n5500.0 0.9\n")

    curve = load_filter_curve(str(path))
    assert list(curve.wavelength_angstrom) == sorted(curve.wavelength_angstrom)


def test_catalogs_are_modest_and_carry_no_transmission_data():
    for catalog in (JOHNSON_COUSINS_FILTERS, SDSS_FILTERS):
        assert 3 <= len(catalog) <= 10
        for info in catalog:
            assert not hasattr(info, "transmission")
            assert not hasattr(info, "wavelength_angstrom")
