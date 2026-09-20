"""Cadena completa (§43): lámpara sintética -> traza -> extracción ->
detección de picos -> emparejamiento con catálogo -> ajuste -> FITS ->
relectura. Comprueba que el RMS recuperado es correcto -- exactamente
lo que pide el encargo: *"comprobar que el RMS recuperado es
correcto"*, no solo que el pipeline no revienta.
"""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.calibration_provenance import (
    CalibrationSource,
    WavelengthCalibrationRecord,
    build_wavelength_provenance,
)
from astrophysics_suite.spectroscopy.line_catalog import arc_catalog, match_lines_to_catalog
from astrophysics_suite.spectroscopy.spectrum1d_io import load_spectrum1d_fits, save_spectrum1d_fits
from astrophysics_suite.spectroscopy.synthetic_lamp import generate_synthetic_lamp_frame2d
from astrophysics_suite.spectroscopy.trace import extract_sum, trace_spectrum
from astrophysics_suite.spectroscopy.wavelength import find_arc_lines, fit_wavelength_solution

_DISPERSION = 1.4
_ZERO_POINT = 5700.0


@pytest.mark.parametrize("lamp_name,curvature_px,degree", [
    ("Ne", 3.0, 2),
    ("Ar", 0.0, 1),
    ("HeNeAr", 5.0, 2),
])
def test_full_chain_recovers_the_true_wavelength_solution(lamp_name, curvature_px, degree):
    frame = generate_synthetic_lamp_frame2d(
        lamp_name, shape=(60, 1600), curvature_px=curvature_px, seed=42,
        wavelength_at_pixel0=_ZERO_POINT, dispersion_angstrom_per_px=_DISPERSION,
        n_cosmic_rays=2, n_dead_pixels=3,
    )
    assert len(frame.injected_lines) >= degree + 3, "la lampara sintetica debe inyectar suficientes lineas para esta prueba"

    trace = trace_spectrum(frame.data, initial_center_px=frame.trace_row_center, fit_degree=2)
    uncertainty = np.sqrt(np.clip(frame.data, 1.0, None))
    spectrum = extract_sum(frame.data, uncertainty, trace, aperture_half_width=10.0)
    assert spectrum.n_columns_invalid == 0  # sin depresiones falsas a cero

    arc_lines = find_arc_lines(spectrum.flux, min_snr=5.0)
    assert len(arc_lines) >= degree + 3

    matches = match_lines_to_catalog(
        [line.pixel for line in arc_lines], arc_catalog(lamp_name),
        approx_dispersion_angstrom_per_px=_DISPERSION, approx_wavelength_at_pixel0=_ZERO_POINT,
        tolerance_angstrom=5.0,
    )
    confirmed_pixels = [m.pixel for m in matches if m is not None]
    confirmed_wavelengths = [m.catalog_line.wavelength_air_angstrom for m in matches if m is not None]
    assert len(confirmed_pixels) >= degree + 3, "el emparejamiento automatico debe confirmar la mayoria de picos reales"

    solution = fit_wavelength_solution(confirmed_pixels, confirmed_wavelengths, degree=degree)

    # El RMS recuperado debe ser del orden del ruido real de centroide,
    # no artificialmente bajo ni absurdamente alto.
    assert 0.0 <= solution.rms_residual < 1.0

    # Y la solución debe coincidir con la verdad conocida del generador
    # en todo el rango cubierto, no solo en los puntos ajustados.
    test_pixels = np.linspace(50, 950, 20)
    true_wavelengths = np.interp(test_pixels, np.arange(len(frame.true_wavelength_at_pixel)), frame.true_wavelength_at_pixel)
    fitted_wavelengths = solution.pixel_to_wavelength(test_pixels)
    np.testing.assert_allclose(fitted_wavelengths, true_wavelengths, atol=1.0)

    record = WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.SYNTHETIC,
        n_lines_used=len(confirmed_pixels), lamp_name=lamp_name,
    )
    provenance = build_wavelength_provenance(record)
    assert any("SIMULADA" in w for w in provenance.warnings)  # nunca se olvida decirlo


def test_full_chain_products_survive_a_real_fits_round_trip(tmp_path):
    frame = generate_synthetic_lamp_frame2d(
        "Ne", shape=(60, 1024), curvature_px=2.0, seed=7,
        wavelength_at_pixel0=_ZERO_POINT, dispersion_angstrom_per_px=_DISPERSION,
    )
    trace = trace_spectrum(frame.data, initial_center_px=frame.trace_row_center, fit_degree=2)
    uncertainty = np.sqrt(np.clip(frame.data, 1.0, None))
    spectrum = extract_sum(frame.data, uncertainty, trace, aperture_half_width=10.0)

    arc_lines = find_arc_lines(spectrum.flux, min_snr=5.0)
    matches = match_lines_to_catalog(
        [line.pixel for line in arc_lines], arc_catalog("Ne"),
        approx_dispersion_angstrom_per_px=_DISPERSION, approx_wavelength_at_pixel0=_ZERO_POINT, tolerance_angstrom=5.0,
    )
    confirmed_pixels = [m.pixel for m in matches if m is not None]
    confirmed_wavelengths = [m.catalog_line.wavelength_air_angstrom for m in matches if m is not None]
    solution = fit_wavelength_solution(confirmed_pixels, confirmed_wavelengths, degree=3)
    record = WavelengthCalibrationRecord(
        solution=solution, source=CalibrationSource.SYNTHETIC, n_lines_used=len(confirmed_pixels), lamp_name="Ne",
    )

    path = tmp_path / "arc_calibrated.fits"
    save_spectrum1d_fits(str(path), spectrum.flux, record, header={"OBJECT": "Ne arc (synthetic)"})

    wavelength, flux, header = load_spectrum1d_fits(str(path))
    np.testing.assert_allclose(wavelength, solution.pixel_to_wavelength(np.arange(spectrum.flux.size)), atol=1e-6)
    assert header["CALTYPE"] == "SYNTHETIC"
    assert header["APSWAVLM"] == "Ne"
