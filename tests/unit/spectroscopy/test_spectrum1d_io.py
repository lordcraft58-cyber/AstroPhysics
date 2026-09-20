"""`spectrum1d_io.py`: WCS espectral real -- lineal exacto para grado
<=1, tabla -TAB exacta (no una aproximación) para grado >=2 -- más
CALTYPE/procedencia completa (§16/§38)."""
from __future__ import annotations

import numpy as np
import pytest
from astropy.io import fits

from astrophysics_suite.spectroscopy.calibration_provenance import CalibrationSource, WavelengthCalibrationRecord
from astrophysics_suite.spectroscopy.spectrum1d_io import (
    load_spectrum1d_fits,
    save_spectrum1d_fits,
    wavelength_header_cards,
)
from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution


def _linear_record(n_lines=6, seed=1):
    rng = np.random.default_rng(seed)
    pixels = np.sort(rng.uniform(20, 980, size=n_lines))
    wavelengths = 1.4 * pixels + 4500.0
    solution = fit_wavelength_solution(list(pixels), list(wavelengths), degree=1)
    return WavelengthCalibrationRecord(solution=solution, source=CalibrationSource.LAMP_REAL, n_lines_used=n_lines, lamp_name="Ne")


def _poly_record(n_lines=8, degree=3, seed=2):
    rng = np.random.default_rng(seed)
    pixels = np.sort(rng.uniform(20, 980, size=n_lines))
    true_coeffs = [1.2e-6, -0.002, 1.35, 4500.0]
    wavelengths = np.polyval(true_coeffs, pixels)
    solution = fit_wavelength_solution(list(pixels), list(wavelengths), degree=degree)
    return WavelengthCalibrationRecord(solution=solution, source=CalibrationSource.SYNTHETIC, n_lines_used=n_lines)


def test_linear_solution_writes_an_exact_linear_wcs_not_a_lookup_table():
    record = _linear_record()
    cards, wave_table = wavelength_header_cards(record, n_pixels=1000)
    assert cards["CTYPE1"] == "WAVE"
    assert wave_table is None
    assert "CRVAL1" in cards and "CDELT1" in cards


def test_polynomial_solution_uses_the_real_tab_lookup_not_a_linear_lie():
    """El punto central del encargo (§16): "no escribir una relación
    lineal falsa si la calibración obtenida es polinómica"."""
    record = _poly_record(degree=3)
    cards, wave_table = wavelength_header_cards(record, n_pixels=1000)
    assert cards["CTYPE1"] == "WAVE-TAB"
    assert "CRVAL1" not in cards  # nunca una recta falsa
    assert "CDELT1" not in cards
    assert wave_table is not None
    assert wave_table.shape == (1000,)
    np.testing.assert_allclose(wave_table, record.solution.pixel_to_wavelength(np.arange(1000)))


def test_linear_round_trip_through_a_real_file_is_exact(tmp_path):
    record = _linear_record()
    flux = np.linspace(100.0, 200.0, 1000)
    path = tmp_path / "linear.fits"
    save_spectrum1d_fits(str(path), flux, record, header={"OBJECT": "Vega", "EXPTIME": 60.0})

    wavelength, flux_read, header = load_spectrum1d_fits(str(path))
    expected = record.solution.pixel_to_wavelength(np.arange(1000))
    np.testing.assert_allclose(wavelength, expected, atol=1e-6)
    np.testing.assert_allclose(flux_read, flux, atol=1.0)  # float32 en disco
    assert header["OBJECT"] == "Vega"
    assert header["EXPTIME"] == pytest.approx(60.0)
    assert header["CALTYPE"] == "REAL"


def test_polynomial_round_trip_through_a_real_file_is_exact_not_approximate(tmp_path):
    record = _poly_record(degree=3)
    flux = np.linspace(50.0, 150.0, 1000)
    path = tmp_path / "poly.fits"
    save_spectrum1d_fits(str(path), flux, record)

    wavelength, _, header = load_spectrum1d_fits(str(path))
    expected = record.solution.pixel_to_wavelength(np.arange(1000))
    np.testing.assert_allclose(wavelength, expected, atol=1e-6)
    assert header["CTYPE1"] == "WAVE-TAB"
    assert header["CALTYPE"] == "SYNTHETIC"


def test_synthetic_calibration_says_so_in_history_and_caltype(tmp_path):
    record = _poly_record(degree=2)
    path = tmp_path / "synthetic.fits"
    save_spectrum1d_fits(str(path), np.zeros(500), record)
    with fits.open(path) as hdul:
        header = hdul[0].header
        assert header["CALTYPE"] == "SYNTHETIC"
        history = " ".join(str(line) for line in header["HISTORY"])
        assert "SIMULADA" in history


def test_real_lamp_calibration_never_claims_to_be_synthetic(tmp_path):
    record = _linear_record()
    path = tmp_path / "real.fits"
    save_spectrum1d_fits(str(path), np.zeros(1000), record)
    with fits.open(path) as hdul:
        header = hdul[0].header
        assert header["CALTYPE"] == "REAL"
        history = " ".join(str(line) for line in header["HISTORY"])
        assert "SIMULADA" not in history


def test_uncertainty_is_written_and_read_back(tmp_path):
    record = _linear_record()
    flux = np.full(1000, 100.0)
    uncertainty = np.full(1000, 5.0)
    path = tmp_path / "with_unc.fits"
    save_spectrum1d_fits(str(path), flux, record, flux_uncertainty=uncertainty)
    with fits.open(path) as hdul:
        assert "UNCERT" in hdul
        np.testing.assert_allclose(hdul["UNCERT"].data, 5.0, atol=1e-3)


def test_loading_a_fits_without_any_recognizable_wcs_raises_instead_of_assuming_pixel_equals_wavelength(tmp_path):
    path = tmp_path / "no_wcs.fits"
    fits.PrimaryHDU(data=np.zeros(100, dtype=np.float32)).writeto(path)
    with pytest.raises(ValueError, match="pixel"):
        load_spectrum1d_fits(str(path))


def test_a_raw_2d_header_never_crashes_the_1d_writer(tmp_path):
    """Hallazgo real: el header crudo de un FITS 2D del usuario (Vega)
    trae NAXIS2 (y NAXIS=2) -- copiarlo al escribir un producto 1D hacía
    que astropy rechazara el archivo entero (`NAXISj keyword out of
    range`). El writer debe descartar TODAS las claves NAXIS* del
    header de origen, no solo NAXIS/NAXIS1."""
    record = _linear_record()
    raw_2d_header = {"NAXIS": 2, "NAXIS1": 1391, "NAXIS2": 1039, "OBJECT": "Vega"}
    path = tmp_path / "from_2d_header.fits"
    save_spectrum1d_fits(str(path), np.full(1000, 100.0), record, header=raw_2d_header)  # no debe lanzar
    with fits.open(path) as hdul:
        assert hdul[0].header["NAXIS"] == 1
        assert hdul[0].header["NAXIS1"] == 1000
        assert "NAXIS2" not in hdul[0].header
        assert hdul[0].header["OBJECT"] == "Vega"


def test_scaling_keywords_from_the_raw_header_are_never_copied(tmp_path):
    record = _linear_record()
    raw_header = {"BZERO": 32768, "BSCALE": 1, "OBJECT": "Vega"}
    path = tmp_path / "no_scaling.fits"
    save_spectrum1d_fits(str(path), np.full(1000, 100.0), record, header=raw_header)
    with fits.open(path) as hdul:
        assert "BZERO" not in hdul[0].header
        assert "BSCALE" not in hdul[0].header
        np.testing.assert_allclose(hdul[0].data, 100.0)


def test_default_bunit_is_adu(tmp_path):
    record = _linear_record()
    path = tmp_path / "adu.fits"
    save_spectrum1d_fits(str(path), np.full(1000, 100.0), record)
    with fits.open(path) as hdul:
        assert hdul[0].header["BUNIT"] == "ADU"


def test_flux_bunit_override_is_never_silently_clobbered_back_to_adu(tmp_path):
    """Hallazgo real: `wavelength_header_cards` fijaba `BUNIT='ADU'`
    incondicionalmente y se aplicaba DESPUÉS del `header` del llamador,
    así que un flujo ya calibrado físicamente (p. ej. por
    `fluxcal.calibrate_flux`) se guardaba etiquetado como si fueran
    cuentas crudas -- incluso pasando un `BUNIT` real en `header`."""
    record = _linear_record()
    path = tmp_path / "physical.fits"
    save_spectrum1d_fits(
        str(path), np.full(1000, 1e-15), record, header={"BUNIT": "esto se ignora, manda flux_bunit"},
        flux_bunit="erg/s/cm2/Angstrom",
    )
    with fits.open(path) as hdul:
        assert hdul[0].header["BUNIT"] == "erg/s/cm2/Angstrom"
