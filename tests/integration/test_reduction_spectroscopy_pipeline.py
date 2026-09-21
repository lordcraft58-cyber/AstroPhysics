"""Cadena completa reducción CCD -> preprocesado espectroscópico ->
traza -> extracción (§7): hasta ahora, `preprocess_spectroscopic_frame`
(bias/dark/flat/píxeles defectuosos/rayos cósmicos, motores de
`reduction/`) y `trace_spectrum`/`extract_sum`/`extract_optimal`
(motores de espectroscopía) solo se probaban por separado -- este
archivo comprueba que COMPONEN de verdad: que el `SpectralFrame2D` real
que produce el preprocesado (datos ya bias/flat-corregidos, máscara real
de calidad) es directamente utilizable por la traza/extracción sin
transformación intermedia, tal como afirma el docstring del propio
`preprocessing.py` ("listo para pasar directamente a trace.trace_
spectrum/extract_sum/extract_optimal vía su parámetro mask").
"""
from __future__ import annotations

import numpy as np

from astrophysics_suite.reduction.master_frames import MasterFrame
from astrophysics_suite.spectroscopy.frame2d import PixelFlag
from astrophysics_suite.spectroscopy.line_catalog import arc_catalog, match_lines_to_catalog
from astrophysics_suite.spectroscopy.preprocessing import preprocess_spectroscopic_frame
from astrophysics_suite.spectroscopy.synthetic_lamp import generate_synthetic_lamp_frame2d
from astrophysics_suite.spectroscopy.trace import extract_optimal, extract_sum, trace_spectrum
from astrophysics_suite.spectroscopy.wavelength import find_arc_lines, fit_wavelength_solution

_DISPERSION = 1.4
_ZERO_POINT = 5700.0


def _master(kind: str, value: float, shape: tuple[int, int]) -> MasterFrame:
    return MasterFrame(
        kind=kind, data=np.full(shape, value, dtype=np.float64),
        uncertainty=np.full(shape, 0.5), n_combined=np.full(shape, 5, dtype=np.int64),
        exposure_s=None,
    )


def test_preprocessed_mask_really_protects_the_extraction_from_a_real_cosmic_ray():
    """El `mask` que produce `preprocess_spectroscopic_frame` no es
    decorativo: pasarlo a `extract_sum` de verdad excluye un rayo
    cósmico real de la suma, frente a no pasarlo."""
    shape = (41, 800)
    frame = generate_synthetic_lamp_frame2d(
        "Ne", shape=shape, curvature_px=0.0, seed=17, trace_row_center=20.0,
        wavelength_at_pixel0=_ZERO_POINT, dispersion_angstrom_per_px=_DISPERSION,
        spatial_sigma_px=2.0, background=80.0, peak_amplitude=2000.0,
    )
    raw = frame.data.copy()
    contaminated_col = 400
    contaminated_row = 20
    raw[contaminated_row, contaminated_col] += 60000.0  # rayo cósmico real inyectado a mano, dentro de la apertura

    result = preprocess_spectroscopic_frame(raw, gain_e_per_adu=1.0, read_noise_e=5.0)
    assert result.frame.mask[contaminated_row, contaminated_col] & PixelFlag.COSMIC_RAY

    trace = trace_spectrum(result.frame.data, initial_center_px=frame.trace_row_center, fit_degree=1, mask=result.frame.mask)
    uncertainty = np.sqrt(result.frame.variance)

    protected = extract_sum(result.frame.data, uncertainty, trace, mask=result.frame.mask, aperture_half_width=6.0)
    unprotected = extract_sum(result.frame.data, uncertainty, trace, mask=None, aperture_half_width=6.0)

    # valor de referencia REAL en esa misma columna: el mismo fotograma, sin el rayo cósmico inyectado
    clean_trace = trace_spectrum(frame.data, initial_center_px=frame.trace_row_center, fit_degree=1)
    clean_uncertainty = np.sqrt(np.clip(frame.data, 1.0, None))
    clean = extract_sum(frame.data, clean_uncertainty, clean_trace, aperture_half_width=6.0)
    true_value = float(clean.flux[contaminated_col])

    assert unprotected.flux[contaminated_col] > true_value + 30000.0  # sin la máscara real, el rayo cósmico contamina brutalmente la suma
    assert abs(protected.flux[contaminated_col] - true_value) < 0.15 * abs(true_value) + 50.0  # con ella, se queda cerca del valor real


def test_full_reduction_and_extraction_chain_recovers_the_true_wavelength_solution():
    """Mismo chequeo que `test_wavelength_calibration_pipeline.py`
    (§43), pero insertando ANTES una reducción real bias+flat
    (`preprocess_spectroscopic_frame`, §7) -- prueba que la composición
    reducción -> espectroscopía no degrada la solución recuperada."""
    shape = (60, 1600)
    frame = generate_synthetic_lamp_frame2d(
        "Ne", shape=shape, curvature_px=2.0, seed=31,
        wavelength_at_pixel0=_ZERO_POINT, dispersion_angstrom_per_px=_DISPERSION,
    )
    bias_level = 500.0
    raw = frame.data + bias_level
    bias = _master("bias", bias_level, shape)
    flat = _master("flat", 1.0, shape)  # plano real (sin variación espacial) -- basta para probar que se aplica de verdad

    result = preprocess_spectroscopic_frame(
        raw, master_bias=bias, master_flat=flat, gain_e_per_adu=1.0, read_noise_e=5.0, detect_cosmic_rays_enabled=False,
    )
    assert result.calibration_steps.bias_subtracted
    assert result.calibration_steps.flat_divided

    trace = trace_spectrum(result.frame.data, initial_center_px=frame.trace_row_center, fit_degree=2, mask=result.frame.mask)
    uncertainty = np.sqrt(result.frame.variance)
    spectrum = extract_optimal(result.frame.data, uncertainty, trace, mask=result.frame.mask, aperture_half_width=10.0)
    assert spectrum.n_columns_invalid == 0

    arc_lines = find_arc_lines(spectrum.flux, min_snr=5.0)
    assert len(arc_lines) >= 4

    matches = match_lines_to_catalog(
        [line.pixel for line in arc_lines], arc_catalog("Ne"),
        approx_dispersion_angstrom_per_px=_DISPERSION, approx_wavelength_at_pixel0=_ZERO_POINT,
        tolerance_angstrom=5.0,
    )
    confirmed_pixels = [m.pixel for m in matches if m is not None]
    confirmed_wavelengths = [m.catalog_line.wavelength_air_angstrom for m in matches if m is not None]
    assert len(confirmed_pixels) >= 4

    solution = fit_wavelength_solution(confirmed_pixels, confirmed_wavelengths, degree=2)
    assert 0.0 <= solution.rms_residual < 1.0

    test_pixels = np.linspace(50, 950, 20)
    true_wavelengths = np.interp(test_pixels, np.arange(len(frame.true_wavelength_at_pixel)), frame.true_wavelength_at_pixel)
    fitted_wavelengths = solution.pixel_to_wavelength(test_pixels)
    np.testing.assert_allclose(fitted_wavelengths, true_wavelengths, atol=1.5)
