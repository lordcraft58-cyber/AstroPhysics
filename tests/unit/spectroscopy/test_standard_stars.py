"""`standard_stars.py`: identidad pública de patrones CALSPEC + lector
real del formato de archivo -- nunca un valor de flujo inventado (§49)."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from astrophysics_suite.spectroscopy.standard_stars import (
    CALSPEC_STANDARD_STARS,
    find_standard_star,
    load_calspec_spectrum,
)


def test_catalog_is_modest_and_nonempty():
    assert 3 <= len(CALSPEC_STANDARD_STARS) <= 20


def test_catalog_entries_never_carry_an_invented_flux_value():
    for star in CALSPEC_STANDARD_STARS:
        assert not hasattr(star, "flux")
        assert not hasattr(star, "reference_flux")


def test_find_standard_star_matches_by_name_and_alias():
    assert find_standard_star("Vega").spectral_type == "A0V"
    assert find_standard_star("alpha Lyr").name == "Vega"
    assert find_standard_star("  vega  ").name == "Vega"


def test_find_standard_star_returns_none_instead_of_a_closest_guess():
    assert find_standard_star("Not A Real Star XYZ") is None


def _write_fake_calspec_file(path, *, with_error_column=True):
    wavelength = np.linspace(3000.0, 9000.0, 50)
    flux = 1e-13 * np.exp(-((wavelength - 6000.0) / 2000.0) ** 2)
    columns = [
        fits.Column(name="WAVELENGTH", format="D", unit="ANGSTROMS", array=wavelength),
        fits.Column(name="FLUX", format="D", unit="FLAM", array=flux),
    ]
    if with_error_column:
        columns.append(fits.Column(name="STATERROR", format="D", unit="FLAM", array=flux * 0.01))
    table_hdu = fits.BinTableHDU.from_columns(columns, name="SPECTRUM")
    primary = fits.PrimaryHDU()
    primary.header["OBJECT"] = "FAKE-STD"
    fits.HDUList([primary, table_hdu]).writeto(path, overwrite=True)
    return wavelength, flux


def test_loads_a_real_calspec_shaped_file_with_error_column(tmp_path):
    path = tmp_path / "fake_std.fits"
    wavelength, flux = _write_fake_calspec_file(path)

    spectrum = load_calspec_spectrum(str(path))

    np.testing.assert_allclose(spectrum.wavelength_angstrom, wavelength)
    np.testing.assert_allclose(spectrum.flux, flux)
    assert spectrum.flux_uncertainty is not None
    assert spectrum.header["OBJECT"] == "FAKE-STD"


def test_loads_a_file_without_an_error_column_leaving_uncertainty_none(tmp_path):
    path = tmp_path / "fake_std_no_err.fits"
    _write_fake_calspec_file(path, with_error_column=False)

    spectrum = load_calspec_spectrum(str(path))
    assert spectrum.flux_uncertainty is None


def test_raises_a_clear_error_for_a_file_without_recognizable_columns(tmp_path):
    path = tmp_path / "not_calspec.fits"
    columns = [fits.Column(name="SOMETHING_ELSE", format="D", array=np.zeros(5))]
    table_hdu = fits.BinTableHDU.from_columns(columns)
    fits.HDUList([fits.PrimaryHDU(), table_hdu]).writeto(path)

    with pytest.raises(ValueError, match="CALSPEC"):
        load_calspec_spectrum(str(path))
