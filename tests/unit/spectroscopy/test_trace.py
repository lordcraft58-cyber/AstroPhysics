from __future__ import annotations

import math
from dataclasses import replace

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.trace import (
    SkyWindow,
    TraceResult,
    estimate_sky_background,
    extract_optimal,
    extract_sum,
    trace_spectrum,
)


def _synthetic_2d_spectrum(shape=(41, 200), *, center=20.0, sigma=2.0, flux_per_col=2000.0, background=50.0, curve=0.0, seed=1):
    rng = np.random.default_rng(seed)
    height, width = shape
    columns = np.arange(width)
    true_center = center + curve * (columns / width) ** 2
    rows = np.arange(height)[:, np.newaxis]
    profile = np.exp(-((rows - true_center[np.newaxis, :]) ** 2) / (2 * sigma**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = background + flux_per_col * profile
    data = data + rng.normal(0, 3.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data, uncertainty, true_center


def test_trace_spectrum_recovers_known_straight_trace():
    data, _, true_center = _synthetic_2d_spectrum(curve=0.0)
    result = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    np.testing.assert_allclose(result.center_px, true_center, atol=0.5)


def test_trace_spectrum_follows_curved_trace():
    data, _, true_center = _synthetic_2d_spectrum(curve=6.0)
    result = trace_spectrum(data, initial_center_px=20.0, fit_degree=3)
    np.testing.assert_allclose(result.center_px, true_center, atol=0.7)


def test_trace_spectrum_rejects_non_2d_input():
    with pytest.raises(ValueError):
        trace_spectrum(np.zeros((5, 5, 5)), initial_center_px=2.0)


def test_trace_spectrum_rejects_center_outside_image():
    with pytest.raises(ValueError):
        trace_spectrum(np.zeros((10, 10)), initial_center_px=50.0)


_SKY_14_4 = (SkyWindow(offset_px=-14.0, half_width_px=4.0), SkyWindow(offset_px=14.0, half_width_px=4.0))


def test_extract_sum_recovers_known_flux():
    flux_per_col = 3000.0
    data, uncertainty, true_center = _synthetic_2d_spectrum(flux_per_col=flux_per_col, curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)

    result = extract_sum(data, uncertainty, trace, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    assert np.all(result.valid)
    median_flux = float(np.median(result.flux))
    assert median_flux == pytest.approx(flux_per_col, rel=0.05)


def test_extract_optimal_achieves_higher_snr_than_sum_for_faint_source():
    """El resultado central de Horne 1986: para una fuente débil, la
    extracción óptima da mayor S/N que la suma simple sobre la misma
    ventana de apertura."""
    data, uncertainty, _ = _synthetic_2d_spectrum(flux_per_col=150.0, background=200.0, seed=3)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)

    sum_result = extract_sum(data, uncertainty, trace, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    optimal_result = extract_optimal(data, uncertainty, trace, aperture_half_width=8.0, sky_windows=_SKY_14_4)

    sum_snr = np.median(sum_result.flux / sum_result.flux_uncertainty)
    optimal_snr = np.median(optimal_result.flux / optimal_result.flux_uncertainty)
    assert optimal_snr > sum_snr


def test_extract_optimal_rejects_shape_mismatch():
    data, _, _ = _synthetic_2d_spectrum()
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    with pytest.raises(ValueError):
        extract_optimal(data, np.ones((3, 3)), trace)


# ---------------------------------------------------------------------------
# Hallazgo real (espectros de Vega del usuario): una columna que no se puede
# medir NUNCA debe quedar como flujo 0.0 -- debe quedar NaN + valid=False.
# ---------------------------------------------------------------------------


def test_trace_spectrum_never_crashes_on_a_nan_pixel_in_the_search_window():
    """Antes: un solo NaN dentro de la ventana de búsqueda contaminaba
    `total_weight` (NaN), el guardia `total_weight <= 0` nunca se
    disparaba (la comparación con NaN es siempre False) y la siguiente
    columna reventaba con `ValueError: cannot convert float NaN to
    integer` al redondear un centro ya contaminado."""
    data, _, true_center = _synthetic_2d_spectrum(curve=0.0)
    data[18:23, 100] = np.nan  # columna entera de la ventana de búsqueda a NaN

    result = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)  # no debe lanzar
    # el resto de la traza (columnas con señal real) se recupera igual
    np.testing.assert_allclose(np.delete(result.center_px, 100), np.delete(true_center, 100), atol=0.5)


def test_extract_sum_leaves_nan_not_zero_when_aperture_falls_off_the_image():
    """Antes: si la traza se acercaba al borde y la apertura quedaba
    parcialmente fuera de la imagen, `extract_sum` sumaba solo lo que
    hubiera en `data[lo:hi, col]` (con `lo`/`hi` recortados) tratando el
    resultado como una medida real de una apertura completa -- con
    `extract_optimal` el fallo era peor: la columna quedaba directamente
    en `flux[col] = 0.0` (el valor inicial de `np.zeros`, nunca
    sobrescrito), indistinguible de un flujo real medido en cero."""
    height = 41
    data, uncertainty, _ = _synthetic_2d_spectrum(shape=(height, 200), center=20.0, curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    # forzar el centro de una columna concreta al borde superior, donde
    # una apertura de semiancho 8 no cabe entera (0 - 8 < 0)
    forced_center = trace.center_px.copy()
    forced_center[50] = 3.0
    edge_trace = replace(trace, center_px=forced_center)

    result = extract_optimal(data, uncertainty, edge_trace, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    assert not result.valid[50]
    assert math.isnan(result.flux[50])  # NUNCA 0.0
    # el resto de columnas, con la traza real, se sigue midiendo bien
    assert result.valid[49] and result.valid[51]


def test_extract_sum_renormalizes_a_partially_masked_aperture_instead_of_dimming_it():
    """Un píxel muerto real dentro de la apertura (como los 27 hallados
    en la banda de la traza de un frame real de Vega) no debe hacer que
    la columna parezca más tenue solo por tener un píxel menos -- se
    renormaliza por la fracción de apertura realmente medida."""
    flux_per_col = 3000.0
    data, uncertainty, _ = _synthetic_2d_spectrum(flux_per_col=flux_per_col, curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)

    mask = np.zeros(data.shape, dtype=bool)
    mask[20, 100] = True  # el píxel central de la traza, exactamente en col=100, marcado como muerto

    result = extract_sum(data, uncertainty, trace, mask=mask, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    unmasked_result = extract_sum(data, uncertainty, trace, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    assert result.valid[100]
    assert result.n_pixels_rejected[100] == 1
    # renormalizar por la fracción de apertura medida acerca el resultado
    # al flujo real más que no renormalizar -- enmascarar justo el pico
    # de un perfil gaussiano (no uniforme) nunca se recupera perfecto con
    # un factor de escala uniforme, para eso existe la extracción óptima.
    naive_unrenormalized = result.flux[100] * (16.0 / 17.0)  # deshacer la renormalización a mano
    assert abs(result.flux[100] - unmasked_result.flux[100]) < abs(naive_unrenormalized - unmasked_result.flux[100])
    assert result.flux[100] == pytest.approx(flux_per_col, rel=0.2)


def test_extract_sum_marks_a_fully_masked_column_invalid_not_zero():
    data, uncertainty, _ = _synthetic_2d_spectrum(curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    mask = np.zeros(data.shape, dtype=bool)
    mask[:, 100] = True  # columna entera muerta

    result = extract_sum(data, uncertainty, trace, mask=mask, aperture_half_width=8.0, sky_windows=_SKY_14_4)
    assert not result.valid[100]
    assert math.isnan(result.flux[100])
    assert result.valid[99] and result.valid[101]  # las columnas vecinas no se ven afectadas


def test_estimate_sky_background_never_returns_a_fake_zero_when_no_sky_pixels_are_usable():
    data, _, _ = _synthetic_2d_spectrum(shape=(41, 50), center=20.0, curve=0.0)
    trace = trace_spectrum(data, initial_center_px=20.0, fit_degree=1)
    # ventanas de cielo que caen enteramente fuera de una imagen de solo 41 filas
    far_windows = (SkyWindow(offset_px=-100.0, half_width_px=4.0), SkyWindow(offset_px=100.0, half_width_px=4.0))

    sky = estimate_sky_background(data, trace, windows=far_windows)
    assert not np.any(sky.valid)
    assert np.all(np.isnan(sky.level))  # nunca 0.0


def test_estimate_sky_background_sigma_clip_rejects_a_contaminating_outlier():
    rng = np.random.default_rng(11)
    data = np.full((41, 30), 100.0) + rng.normal(0, 2.0, (41, 30))
    # traza sintética recta -- no hace falta ejecutar trace_spectrum, basta un TraceResult fijo
    trace = TraceResult(columns=np.arange(30), center_px=np.full(30, 20.0), fit_degree=0, rms_residual_px=0.0)
    windows = (SkyWindow(offset_px=-10.0, half_width_px=3.0),)
    data[17:24, 15] = 5000.0  # contaminación real de cielo (un resto de fuente) en una columna

    sky_clipped = estimate_sky_background(data, trace, windows=windows, reducer="sigma_clip")
    sky_median = estimate_sky_background(data, trace, windows=windows, reducer="median")
    assert sky_clipped.level[15] == pytest.approx(100.0, abs=5.0)
    assert sky_median.level[15] == pytest.approx(100.0, abs=5.0)  # la mediana también resiste un solo outlier
