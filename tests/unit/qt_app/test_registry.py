"""Los adaptadores de proceso son numpy puro -- comprobables sin Qt. No
deben reimplementar ninguna matemática, solo traducir parámetros/resultados;
estas pruebas confirman que la traducción en sí es correcta."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.wavelength import fit_wavelength_solution
from qt_app.processes.registry import _saturation_mask_from_header, _uncertainty_adu, build_process_registry


def _get(process_id: str):
    registry = build_process_registry()
    matches = [p for p in registry if p.process_id == process_id]
    assert len(matches) == 1, f"proceso {process_id} no encontrado o duplicado"
    return matches[0]


def _default_params(process):
    return {p.name: p.default for p in process.parameters}


def test_registry_has_no_duplicate_process_ids():
    registry = build_process_registry()
    ids = [p.process_id for p in registry]
    assert len(ids) == len(set(ids))


def test_registry_covers_all_expected_categories():
    # "Astrometría" ya no aparece en el árbol de procesos: sus dos
    # capacidades (ajuste de WCS, registro por WCS compartido) viven en
    # diálogos dedicados del menú "Astrometría" (Fase 13), retiradas de
    # aquí por el mismo motivo que imtools.arithmetic y los fotogramas
    # maestros de ccdred.
    registry = build_process_registry()
    categories = {p.category for p in registry}
    assert categories == {"Reducción CCD", "Utilidades de imagen", "Fotometría", "Espectroscopía"}


def test_unwired_processes_have_no_run_and_are_flagged():
    registry = build_process_registry()
    unwired = [p for p in registry if not p.is_wired]
    assert unwired  # deben quedar pendientes documentados, no ocultos
    for process in unwired:
        assert process.run is None
        assert process.description  # explica qué falta, no queda en blanco


def test_wired_processes_are_actually_callable():
    registry = build_process_registry()
    wired = [p for p in registry if p.is_wired]
    assert len(wired) >= 3
    for process in wired:
        assert callable(process.run)


def test_cosmic_ray_removal_process_flags_injected_spike():
    process = _get("imtools.cosmic_rays")
    data = np.full((40, 40), 200.0)
    data[20, 20] += 6000.0
    result = process.run(data, _default_params(process))
    assert result.output_data is not None
    assert abs(result.output_data[20, 20] - 200.0) < 50.0
    assert "1 píxel" in result.summary or "píxel(es)" in result.summary


def test_overscan_subtraction_process_trims_and_subtracts():
    height, width = 30, 50
    data = np.full((height, width), 100.0)
    data[:, width - 20 :] = 500.0  # franja de overscan con un nivel distinto
    process = _get("reduction.overscan")
    result = process.run(data, _default_params(process))
    assert result.output_data is not None
    assert result.output_data.shape == (height, width - 20)
    np.testing.assert_allclose(result.output_data, -400.0)


def test_aperture_photometry_process_reports_positive_flux_for_picked_star():
    yy, xx = np.mgrid[0:61, 0:61]
    data = 100.0 + 20000.0 / (2 * math.pi * 3.0**2) * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * 3.0**2))
    process = _get("photometry.aperture")
    assert process.requires_picking == 1
    params = _default_params(process)
    params["_picked_points"] = [(30.0, 30.0)]
    result = process.run(data, params)
    assert result.output_data is None  # es un proceso de medición, no transforma la imagen
    assert "Flujo neto" in result.summary
    assert "marcado a clic" in result.log_lines[0]


def test_aperture_photometry_process_rejects_no_picked_points():
    process = _get("photometry.aperture")
    data = np.full((20, 20), 100.0)
    params = _default_params(process)
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "posición" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin posición marcada")


def test_aperture_photometry_process_fits_curve_of_growth_when_requested():
    shape = (101, 101)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    sigma = 2.8
    data = 200.0 + 40000.0 / (2 * math.pi * sigma**2) * np.exp(-(((xx - 50) ** 2 + (yy - 50) ** 2)) / (2 * sigma**2))
    process = _get("photometry.aperture")
    params = _default_params(process)
    params["_picked_points"] = [(50.0, 50.0)]
    params["radius_px"] = 6.0
    params["sky_r_in"] = 30.0
    params["sky_r_out"] = 40.0
    params["fit_curve_of_growth"] = True

    result = process.run(data, params)

    assert "Curva de crecimiento" in result.log_lines[-1]
    assert "radio óptimo" in result.log_lines[-1]
    assert result.table is not None
    assert result.table.columns == ("radius_px", "net_flux", "snr")
    assert len(result.table.rows) >= 4


def test_aperture_photometry_process_skips_curve_of_growth_by_default():
    data = 100.0 + np.zeros((41, 41))
    process = _get("photometry.aperture")
    params = _default_params(process)
    assert params["fit_curve_of_growth"] is False
    assert params["auto_detect"] is False
    params["_picked_points"] = [(20.0, 20.0)]
    result = process.run(data, params)
    assert result.table is None


def test_zeropoint_process_requires_unlimited_picking():
    process = _get("photometry.zeropoint")
    assert process.requires_picking == 0


def test_zeropoint_process_rejects_no_picked_points():
    process = _get("photometry.zeropoint")
    data = np.full((20, 20), 100.0)
    params = _default_params(process)
    params["_picked_points"] = []
    params["_wcs"] = object()
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "posición" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin posiciones marcadas")


def test_zeropoint_process_rejects_missing_wcs():
    process = _get("photometry.zeropoint")
    data = np.full((20, 20), 100.0)
    params = _default_params(process)
    params["_picked_points"] = [(10.0, 10.0)]
    params["_wcs"] = None
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "WCS" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin WCS")


def test_zeropoint_process_fits_real_zeropoint_against_mocked_gaia(monkeypatch):
    from astropy.wcs import WCS

    import qt_app.processes.registry as registry_module

    shape = (61, 61)
    star_positions = [(20.0, 20.0, 30000.0), (40.0, 35.0, 12000.0)]
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    data = np.full(shape, 100.0)
    sigma = 2.0
    for x0, y0, flux in star_positions:
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [30.0, 30.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    true_zeropoint = 24.5
    gaia_rows = []
    for x0, y0, flux in star_positions:
        ra, dec = wcs.celestial.all_pix2world(x0, y0, 0)
        instrumental_mag = -2.5 * math.log10(flux)
        catalog_mag = instrumental_mag + true_zeropoint
        gaia_rows.append({"ra_deg": float(ra), "dec_deg": float(dec), "mag_g": catalog_mag, "source_id": f"{x0}-{y0}"})

    monkeypatch.setattr(registry_module, "query_gaia_neighbors", lambda ra, dec, **kwargs: gaia_rows)

    process = _get("photometry.zeropoint")
    params = _default_params(process)
    params["_picked_points"] = [(x0, y0) for x0, y0, _ in star_positions]
    params["_wcs"] = wcs

    result = process.run(data, params)

    assert result.output_data is None
    assert "Punto cero" in result.summary
    recovered = float(result.summary.split("=")[1].split("±")[0].strip())
    assert recovered == pytest.approx(true_zeropoint, abs=0.3)
    assert len(result.log_lines) == 2

    assert result.table is not None
    assert result.table.columns == ("star", "x", "y", "ra", "dec", "instrumental_mag", "catalog_mag", "separation", "usada")
    assert len(result.table.rows) == 2
    assert result.table.rows[0][0] == 1  # numeración de estrella desde 1
    # Ambas estrellas son consistentes con el mismo punto cero real -- el
    # sigma-clip de `fit_zeropoint` no debería rechazar ninguna, y esa
    # información real (por índice, antes perdida) ahora llega a la tabla.
    assert result.table.rows[0][-1] == "sí"
    assert result.table.rows[1][-1] == "sí"


def test_zeropoint_process_rejects_when_no_star_matches_gaia(monkeypatch):
    from astropy.wcs import WCS

    import qt_app.processes.registry as registry_module

    wcs = WCS(naxis=2)
    wcs.wcs.crpix = [15.0, 15.0]
    wcs.wcs.cdelt = [-1.0 / 3600.0, 1.0 / 3600.0]
    wcs.wcs.crval = [150.0, 2.0]
    wcs.wcs.ctype = ["RA---TAN", "DEC--TAN"]

    monkeypatch.setattr(registry_module, "query_gaia_neighbors", lambda ra, dec, **kwargs: [])

    process = _get("photometry.zeropoint")
    data = np.full((30, 30), 100.0)
    params = _default_params(process)
    params["_picked_points"] = [(15.0, 15.0)]
    params["_wcs"] = wcs

    try:
        process.run(data, params)
    except ValueError as exc:
        assert "Gaia" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin ningún emparejamiento Gaia")


def test_continuum_fit_process_runs_on_central_row():
    data = np.full((21, 200), 100.0)
    data[10, 50:55] += 300.0  # línea de emisión en la fila central
    process = _get("spectroscopy.continuum")
    result = process.run(data, _default_params(process))
    assert result.output_data is None
    assert "Continuo ajustado" in result.summary
    plot_data = result.artifacts["spectrum"]
    assert [s.label for s in plot_data.series] == ["Flujo", "Continuo ajustado"]
    assert plot_data.series[1].style == "dashed"


def test_psf_photometry_process_requires_picking_and_recovers_flux():
    process = _get("photometry.psf")
    assert process.requires_picking == 0  # ilimitado

    sigma = 2.0
    true_flux = 30000.0
    yy, xx = np.mgrid[0:61, 0:61]
    data = 100.0 + true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * sigma**2))

    params = _default_params(process)
    params["_picked_points"] = [(30.0, 30.0)]
    result = process.run(data, params)

    assert result.output_data is None
    assert len(result.log_lines) == 1
    assert "flujo=" in result.log_lines[0]
    logged_flux = float(result.log_lines[0].split("flujo=")[1].split(" ")[0])
    assert logged_flux == pytest.approx(true_flux, rel=0.05)


def test_psf_photometry_process_refines_position_when_requested():
    process = _get("photometry.psf")
    sigma = 2.0
    true_flux = 30000.0
    true_x, true_y = 30.4, 29.6
    yy, xx = np.mgrid[0:61, 0:61]
    data = 100.0 + true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - true_x) ** 2 + (yy - true_y) ** 2)) / (2 * sigma**2))

    params = _default_params(process)
    params["_picked_points"] = [(true_x + 1.4, true_y - 1.1)]  # clic deliberadamente descentrado
    params["refine_positions"] = True
    result = process.run(data, params)

    assert "allstar" in result.summary
    assert "desplazamiento" in result.log_lines[0]
    assert result.table is not None
    refined_x, refined_y = result.table.rows[0][0], result.table.rows[0][1]
    assert refined_x == pytest.approx(true_x, abs=0.2)
    assert refined_y == pytest.approx(true_y, abs=0.2)


def test_psf_photometry_process_reports_fit_diagnostics_when_requested():
    process = _get("photometry.psf")
    sigma = 2.0
    true_flux = 30000.0
    yy, xx = np.mgrid[0:61, 0:61]
    data = 100.0 + true_flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - 30) ** 2 + (yy - 30) ** 2)) / (2 * sigma**2))

    params = _default_params(process)
    params["_picked_points"] = [(30.0, 30.0)]
    params["report_fit_diagnostics"] = True
    result = process.run(data, params)

    assert result.output_data is not None  # imagen de residuo
    assert any("chi" in line.lower() for line in result.log_lines)


def test_psf_photometry_process_uses_moffat_profile_when_requested():
    process = _get("photometry.psf")
    alpha, beta = 3.0, 2.5
    true_flux = 30000.0
    from astrophysics_suite.photometry.psf import MoffatPSF

    psf = MoffatPSF(alpha=alpha, beta=beta)
    yy, xx = np.mgrid[0:61, 0:61]
    profile = psf.evaluate((xx - 30.0).astype(float), (yy - 30.0).astype(float))
    data = 100.0 + true_flux * profile

    params = _default_params(process)
    params["_picked_points"] = [(30.0, 30.0)]
    params["use_moffat_psf"] = True
    params["moffat_alpha_px"] = alpha
    params["moffat_beta"] = beta
    result = process.run(data, params)

    logged_flux = float(result.log_lines[0].split("flujo=")[1].split(" ")[0])
    assert logged_flux == pytest.approx(true_flux, rel=0.05)


def test_psf_photometry_process_uses_empirical_psf_when_requested():
    shape = (81, 81)
    sigma = 2.0
    reference_flux, target_flux = 30000.0, 18000.0
    ref_x, ref_y = 25.0, 25.0
    tgt_x, tgt_y = 55.0, 55.0
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    background = 100.0
    data = np.full(shape, background)
    for x0, y0, flux in ((ref_x, ref_y, reference_flux), (tgt_x, tgt_y, target_flux)):
        data = data + flux / (2 * math.pi * sigma**2) * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))

    process = _get("photometry.psf")
    params = _default_params(process)
    params["use_empirical_psf"] = True
    params["_psf_reference_points"] = [(ref_x, ref_y)]
    params["_picked_points"] = [(tgt_x, tgt_y)]

    result = process.run(data, params)

    assert "PSF empírica construida" in result.log_lines[0]
    logged_flux = float(result.log_lines[1].split("flujo=")[1].split(" ")[0])
    assert logged_flux == pytest.approx(target_flux, rel=0.1)


def test_psf_photometry_process_rejects_empirical_psf_without_reference_points():
    process = _get("photometry.psf")
    data = np.full((40, 40), 100.0)
    params = _default_params(process)
    params["use_empirical_psf"] = True
    params["_picked_points"] = [(20.0, 20.0)]
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "referencia" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin estrellas de referencia para la PSF empírica")


def test_psf_photometry_process_always_returns_measurement_table():
    process = _get("photometry.psf")
    data = np.full((61, 61), 100.0)
    params = _default_params(process)
    params["_picked_points"] = [(30.0, 30.0), (40.0, 40.0)]
    result = process.run(data, params)
    assert result.table is not None
    assert result.table.columns == ("x", "y", "flux", "flux_uncertainty")
    assert len(result.table.rows) == 2


def test_psf_photometry_process_rejects_no_picked_points():
    process = _get("photometry.psf")
    data = np.full((20, 20), 100.0)
    params = _default_params(process)
    params["_picked_points"] = []
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "posición" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError sin posiciones marcadas")


def test_spectral_trace_process_requires_one_point_and_produces_a_real_spectrum():
    process = _get("spectroscopy.trace")
    assert process.requires_picking == 1

    height, width = 41, 150
    yy, xx = np.mgrid[0:height, 0:width]
    flux_per_col = 3000.0
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + flux_per_col * profile

    process_params = _default_params(process)
    process_params["_picked_points"] = [(0.0, 20.0)]
    result = process.run(data, process_params)

    assert result.output_data is None
    assert "Traza extraída" in result.summary
    plot_data = result.artifacts["spectrum"]
    assert len(plot_data.series) == 1
    assert plot_data.series[0].x.size == width
    assert plot_data.series[0].y.size == width


def test_spectral_trace_process_supports_mean_extraction():
    # §3: modo "media" -- flujo por píxel de apertura, no el total.
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    flux_per_col = 3000.0
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + flux_per_col * profile

    process = _get("spectroscopy.trace")
    params_sum = _default_params(process)
    params_sum["extraction_method"] = "suma simple"
    params_sum["_picked_points"] = [(0.0, 20.0)]
    result_sum = process.run(data, params_sum)

    params_mean = _default_params(process)
    params_mean["extraction_method"] = "media (§3)"
    params_mean["_picked_points"] = [(0.0, 20.0)]
    result_mean = process.run(data, params_mean)

    aperture_half_width = params_mean["aperture_half_width"]
    nominal_pixels = 2 * aperture_half_width + 1
    flux_sum = result_sum.artifacts["spectrum"].series[0].y
    flux_mean = result_mean.artifacts["spectrum"].series[0].y
    np.testing.assert_allclose(flux_mean, flux_sum / nominal_pixels, equal_nan=True)


def test_spectral_trace_process_applies_real_sky_smoothing_when_requested():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    flux_per_col = 3000.0
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + flux_per_col * profile

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["sky_smooth_degree"] = 2
    params["_picked_points"] = [(0.0, 20.0)]
    result = process.run(data, params)

    assert "polinomio real de grado 2" in result.summary


def test_spectral_trace_process_rejects_wrong_number_of_points():
    process = _get("spectroscopy.trace")
    data = np.full((30, 30), 100.0)
    params = _default_params(process)
    params["_picked_points"] = [(1.0, 1.0), (2.0, 2.0)]
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "un clic" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError con más de un punto marcado")


def test_qc_report_process_requires_one_point_and_reports_six_real_metrics():
    process = _get("spectroscopy.qc_report")
    assert process.requires_picking == 1

    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 6000.0 * profile

    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    result = process.run(data, params)

    assert result.output_data is None
    assert "estado global" in result.summary
    assert result.table is not None
    assert [row[0] for row in result.table.rows] == [
        "Traza espacial", "Calibración en longitud de onda", "Rango de longitud de onda", "Dispersión (centro)",
        "Relación señal/ruido", "Calidad de píxeles",
    ]
    # sin calibración en longitud de onda: N/D real en las tres filas que dependen de ella, nunca inventado
    rows_by_name = {row[0]: row for row in result.table.rows}
    assert rows_by_name["Calibración en longitud de onda"][1] == "N/D"
    assert rows_by_name["Rango de longitud de onda"][1] == "N/D"
    assert rows_by_name["Dispersión (centro)"][1] == "N/D"
    assert len(result.log_lines) == 6


def test_qc_report_process_includes_real_wavelength_metrics_when_a_solution_exists():
    process = _get("spectroscopy.qc_report")
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 6000.0 * profile

    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    params["_wavelength_solution"] = fit_wavelength_solution([0.0, float(width - 1)], [4000.0, 4300.0], degree=1)
    result = process.run(data, params)

    rows_by_name = {row[0]: row for row in result.table.rows}
    assert rows_by_name["Calibración en longitud de onda"][1] == "OK"  # RMS=0 para un ajuste lineal exacto de 2 puntos
    range_row = rows_by_name["Rango de longitud de onda"]
    assert range_row[1] == "OK"
    assert "4000.0" in range_row[2] and "4300.0" in range_row[2]
    dispersion_row = rows_by_name["Dispersión (centro)"]
    assert dispersion_row[1] == "OK"
    expected_dispersion = 300.0 / 149.0  # (4300-4000) Å / (149-0) px, solución lineal exacta
    assert dispersion_row[2] == f"{expected_dispersion:.4f} Å/px"


def test_qc_report_process_rejects_wrong_number_of_points():
    process = _get("spectroscopy.qc_report")
    data = np.full((30, 30), 100.0)
    params = _default_params(process)
    params["_picked_points"] = [(1.0, 1.0), (2.0, 2.0)]
    with pytest.raises(ValueError):
        process.run(data, params)


def test_crop_process_requires_exactly_two_points():
    process = _get("imtools.crop")
    assert process.requires_picking == 2

    data = np.arange(100).reshape(10, 10).astype(np.float64)
    params = _default_params(process)
    params["_picked_points"] = [(2.0, 3.0), (6.0, 7.0)]  # (x, y): columnas 2-6, filas 3-7
    result = process.run(data, params)

    assert result.output_data is not None
    assert result.output_data.shape == (5, 5)  # filas 3..7 inclusive, columnas 2..6 inclusive
    np.testing.assert_array_equal(result.output_data, data[3:8, 2:7])


def test_crop_process_works_regardless_of_click_order():
    process = _get("imtools.crop")
    data = np.arange(100).reshape(10, 10).astype(np.float64)
    params = _default_params(process)
    params["_picked_points"] = [(6.0, 7.0), (2.0, 3.0)]  # esquinas invertidas
    result = process.run(data, params)

    np.testing.assert_array_equal(result.output_data, data[3:8, 2:7])


def test_crop_process_rejects_wrong_number_of_points():
    process = _get("imtools.crop")
    data = np.zeros((10, 10))
    params = _default_params(process)
    params["_picked_points"] = [(1.0, 1.0)]
    try:
        process.run(data, params)
    except ValueError as exc:
        assert "dos clics" in str(exc)
    else:
        raise AssertionError("se esperaba ValueError con un solo punto marcado")


def test_normalize_process_maps_to_zero_one_range():
    process = _get("imtools.normalize")
    rng = np.random.default_rng(1)
    data = rng.normal(1000.0, 50.0, (40, 40))
    params = _default_params(process)

    result = process.run(data, params)

    assert result.output_data is not None
    assert result.output_data.shape == data.shape
    assert result.output_data.min() >= -0.5  # percentiles 1/99 pueden dejar algún valor fuera de [0,1] por diseño
    assert result.output_data.max() <= 1.5


def test_statistics_process_reports_known_values_and_builds_histogram_image():
    process = _get("imtools.statistics")
    data = np.arange(1, 101, dtype=np.float64).reshape(10, 10)
    params = _default_params(process)
    params["bins"] = 10

    result = process.run(data, params)

    assert result.output_data is not None
    assert result.output_data.shape == (100, 10)  # imagen de barras: alta x contenedores
    assert "media=50.50" in result.summary
    assert "n=100" in result.summary
    assert len(result.log_lines) == 2


def test_line_measurement_process_produces_a_spectrum_with_a_measurement_window_marker():
    width = 200
    columns = np.arange(width, dtype=np.float64)
    line_pixel, continuum_level, amplitude = 100.0, 500.0, 4000.0
    row = continuum_level + amplitude * np.exp(-((columns - line_pixel) ** 2) / (2 * 3.0**2))
    data = np.tile(row, (21, 1))

    process = _get("spectroscopy.line")
    params = _default_params(process)
    params["_picked_points"] = [(line_pixel, 10.0)]
    result = process.run(data, params)

    assert result.output_data is None
    plot_data = result.artifacts["spectrum"]
    assert [s.label for s in plot_data.series] == ["Flujo", "Continuo ajustado"]
    assert len(plot_data.markers) == 1
    marker = plot_data.markers[0]
    assert marker.x_start < line_pixel < marker.x_end


def _synthetic_gaussian_row(*, width=200, line_pixel=100.0, continuum_level=500.0, amplitude=4000.0, sigma=3.0):
    columns = np.arange(width, dtype=np.float64)
    row = continuum_level + amplitude * np.exp(-((columns - line_pixel) ** 2) / (2 * sigma**2))
    return np.tile(row, (21, 1))


def test_line_profile_fit_process_reports_only_pixel_units_without_wavelength_calibration():
    # sin calibración en longitud de onda ajustada (`_wavelength_solution`
    # ausente, tal como llega cuando `view.fitted_wavelength_solution` es
    # `None`), la resolución real (§32) no puede calcularse -- debe
    # informarse honestamente como no disponible, nunca asumiendo una
    # dispersión Å/píxel inventada.
    data = _synthetic_gaussian_row()
    process = _get("spectroscopy.line_profile_fit")
    params = _default_params(process)
    params["_picked_points"] = [(100.0, 10.0)]

    result = process.run(data, params)

    assert "λ=" not in result.summary
    assert any("no disponible" in line for line in result.log_lines)
    assert result.table.columns[-3:] == ("center_wavelength_angstrom", "fwhm_angstrom", "resolution")
    assert all(math.isnan(value) for value in result.table.rows[0][-3:])


def test_line_profile_fit_process_reports_real_resolution_with_a_wavelength_solution():
    # dispersión lineal real conocida: 2.0 Å/píxel, 6000.0 Å en el píxel 0.
    dispersion_angstrom_per_px = 2.0
    wave_at_pixel_0 = 6000.0
    pixel_centers = [0.0, 50.0, 100.0, 150.0, 199.0]
    known_wavelengths = [wave_at_pixel_0 + dispersion_angstrom_per_px * p for p in pixel_centers]
    solution = fit_wavelength_solution(pixel_centers, known_wavelengths, degree=1)

    line_pixel, sigma = 100.0, 3.0
    data = _synthetic_gaussian_row(line_pixel=line_pixel, sigma=sigma)
    process = _get("spectroscopy.line_profile_fit")
    params = _default_params(process)
    params["_picked_points"] = [(line_pixel, 10.0)]
    params["_wavelength_solution"] = solution

    result = process.run(data, params)

    expected_center_angstrom = wave_at_pixel_0 + dispersion_angstrom_per_px * line_pixel
    expected_fwhm_angstrom = 2.3548 * sigma * dispersion_angstrom_per_px
    expected_resolution = expected_center_angstrom / expected_fwhm_angstrom

    assert "λ=" in result.summary and "R≈" in result.summary
    assert any("Resolución espectral real" in line for line in result.log_lines)

    center_angstrom, fwhm_angstrom, resolution = result.table.rows[0][-3:]
    assert center_angstrom == pytest.approx(expected_center_angstrom, abs=1.0)
    assert fwhm_angstrom == pytest.approx(expected_fwhm_angstrom, rel=0.05)
    assert resolution == pytest.approx(expected_resolution, rel=0.1)


def test_identify_lines_process_reports_both_air_and_vacuum_catalog_wavelengths():
    # conecta air_vacuum.py a un consumidor real (§24): el catálogo de
    # objeto ya da la longitud de onda en aire (convención NIST ASD);
    # ahora la tabla también informa su equivalente en vacío real.
    from astrophysics_suite.spectroscopy.air_vacuum import air_to_vacuum

    h_alpha = 6562.8
    width = 3000
    wavelength = np.linspace(6400.0, 6700.0, width)
    flux = 100.0 - 15.0 * np.exp(-((wavelength - h_alpha) ** 2) / (2 * 1.3**2))
    data = np.tile(flux, (21, 1))

    process = _get("spectroscopy.identify_lines")
    params = _default_params(process)
    params["catalog"] = "Balmer (H, estelar)"
    params["_wavelength_solution"] = fit_wavelength_solution(
        [0.0, float(width - 1)], [float(wavelength[0]), float(wavelength[-1])], degree=1
    )

    result = process.run(data, params)

    assert result.table.columns[:5] == (
        "catalog_label", "element", "detected_wavelength", "catalog_wavelength_air", "catalog_wavelength_vacuum",
    )
    row = next(r for r in result.table.rows if r[0] == "H-alpha")
    catalog_air, catalog_vacuum = row[3], row[4]
    assert catalog_air == pytest.approx(h_alpha)
    assert catalog_vacuum == pytest.approx(air_to_vacuum(h_alpha))
    assert catalog_vacuum > catalog_air


def test_reference_star_calibration_process_infers_a_provisional_wavelength_solution():
    # estrella sintética A0V-like con Balmer real en posiciones conocidas
    true_wave0, true_dispersion = 4000.0, 2.0
    width = 2000
    pixel = np.arange(width, dtype=np.float64)
    continuum_level = 200.0
    flux = np.full(width, continuum_level)
    from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - true_wave0) / true_dispersion
        if 0 <= true_pixel < width:
            flux -= 40.0 * np.exp(-((pixel - true_pixel) ** 2) / (2 * 2.5**2))
    data = np.tile(flux, (21, 1))

    process = _get("spectroscopy.reference_star_calibration")
    params = _default_params(process)
    params["catalog"] = "Balmer (H, estelar)"
    params["approx_dispersion_angstrom_per_px"] = true_dispersion * 1.01
    params["approx_wavelength_at_pixel0"] = true_wave0 + 10.0
    params["tolerance_angstrom"] = 40.0
    params["_header"] = {"OBJECT": "Vega (sintética)"}

    result = process.run(data, params)

    assert "PROVISIONAL" in result.summary
    assert "Vega (sintética)" in result.summary
    record = result.artifacts["wavelength_calibration_record"]
    assert record.reference_object == "Vega (sintética)"
    assert record.source.value == "reference_star"
    assert record.solution.pixel_to_wavelength(0.0) == pytest.approx(true_wave0, abs=5.0)
    assert result.artifacts["wavelength_calibration_spectrum"] is not None
    assert result.table is not None and len(result.table.rows) == 1


def test_reference_star_calibration_process_falls_back_to_an_honest_placeholder_without_a_real_object_header():
    from astrophysics_suite.spectroscopy.line_catalog import BALMER_LINES

    true_wave0, true_dispersion = 4000.0, 2.0
    width = 2000
    pixel = np.arange(width, dtype=np.float64)
    flux = np.full(width, 200.0)
    for line in BALMER_LINES:
        true_pixel = (line.wavelength_air_angstrom - true_wave0) / true_dispersion
        if 0 <= true_pixel < width:
            flux -= 40.0 * np.exp(-((pixel - true_pixel) ** 2) / (2 * 2.5**2))
    data = np.tile(flux, (21, 1))

    process = _get("spectroscopy.reference_star_calibration")
    params = _default_params(process)
    params["catalog"] = "Balmer (H, estelar)"
    params["approx_dispersion_angstrom_per_px"] = true_dispersion * 1.01
    params["approx_wavelength_at_pixel0"] = true_wave0 + 10.0
    params["tolerance_angstrom"] = 40.0

    result = process.run(data, params)
    record = result.artifacts["wavelength_calibration_record"]
    assert "sin nombre" in record.reference_object


def test_reference_star_calibration_process_raises_honestly_when_nothing_matches():
    data = np.full((21, 200), 200.0)  # continuo puro, sin ninguna línea real
    process = _get("spectroscopy.reference_star_calibration")
    params = _default_params(process)
    with pytest.raises(ValueError):
        process.run(data, params)


def test_multi_aperture_process_produces_one_spectrum_series_per_aperture():
    height, width = 60, 150
    rows = np.arange(height)[:, np.newaxis]
    data = np.full((height, width), 80.0)
    for center, flux in ((15.0, 3000.0), (45.0, 5000.0)):
        profile = np.exp(-((rows - center) ** 2) / (2 * 2.0**2))
        profile /= profile.sum(axis=0, keepdims=True)
        data = data + flux * profile

    process = _get("spectroscopy.multiaperture")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 15.0), (0.0, 45.0)]
    result = process.run(data, params)

    assert result.output_data is None
    plot_data = result.artifacts["spectrum"]
    assert len(plot_data.series) == 2
    assert plot_data.series[0].color != plot_data.series[1].color
    assert all(s.x.size == width for s in plot_data.series)


def test_saturation_mask_from_header_inactive_without_a_real_saturate_value():
    data = np.full((5, 5), 100.0)

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, {})
    assert mask is None and n_saturated == 0 and saturate_adu is None

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, {"_header": {}})
    assert mask is None and n_saturated == 0 and saturate_adu is None

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, {"_header": {"SATURATE": "no-numerico"}})
    assert mask is None and n_saturated == 0 and saturate_adu is None

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, {"_header": {"SATURATE": -1.0}})
    assert mask is None and n_saturated == 0 and saturate_adu is None


def test_saturation_mask_from_header_detects_real_saturated_pixels():
    data = np.full((5, 5), 100.0)
    data[0, 0] = 500.0
    data[2, 3] = 500.0

    mask, n_saturated, saturate_adu = _saturation_mask_from_header(data, {"_header": {"SATURATE": 400.0}})

    assert n_saturated == 2
    assert saturate_adu == 400.0
    assert mask is not None
    assert mask.shape == data.shape


def test_spectral_trace_process_excludes_saturated_pixels_and_reports_them():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    flux_per_col = 3000.0
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + flux_per_col * profile
    # umbral elegido para saturar SOLO la fila del pico (fila 20, ~678 ADU
    # en este perfil) y no las filas vecinas (~608 ADU) -- deja evidencia
    # real de sobra para que la extracción por suma simple siga siendo
    # posible, en vez de vaciar toda la apertura.
    saturate_adu = 650.0
    n_expected_saturated = int(np.count_nonzero(data >= 0.999 * saturate_adu))
    assert n_expected_saturated == width  # una fila entera (la del pico) en las 150 columnas

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["extraction_method"] = "suma simple"
    params["_picked_points"] = [(0.0, 20.0)]
    params["_header"] = {"SATURATE": saturate_adu}
    result = process.run(data, params)

    assert "saturado" in result.summary
    assert str(n_expected_saturated) in result.summary


def test_spectral_trace_process_stays_inactive_without_a_real_saturate_header():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    params["_header"] = {}  # sin SATURATE real -- nunca se inventa un umbral
    result = process.run(data, params)

    assert "saturado" not in result.summary


def test_uncertainty_adu_falls_back_to_sqrt_adu_without_a_real_gain():
    data = np.array([100.0, 400.0])

    uncertainty, note = _uncertainty_adu(data, {})
    np.testing.assert_allclose(uncertainty, np.sqrt(data))
    assert note is None

    uncertainty, note = _uncertainty_adu(data, {"_header": {"GAIN": "no-numerico"}})
    np.testing.assert_allclose(uncertainty, np.sqrt(data))
    assert note is None

    uncertainty, note = _uncertainty_adu(data, {"_header": {"GAIN": -2.0}})
    np.testing.assert_allclose(uncertainty, np.sqrt(data))
    assert note is None


def test_uncertainty_adu_uses_real_gain_and_read_noise_when_available():
    data = np.array([100.0, 400.0])

    uncertainty, note = _uncertainty_adu(data, {"_header": {"GAIN": 2.0, "RDNOISE": 5.0}})

    expected = np.sqrt(data * 2.0 + 5.0**2) / 2.0
    np.testing.assert_allclose(uncertainty, expected)
    assert "GAIN=2" in note
    assert "RDNOISE=5" in note


def test_uncertainty_adu_uses_real_gain_without_read_noise():
    data = np.array([100.0])

    uncertainty, note = _uncertainty_adu(data, {"_header": {"GAIN": 2.0}})

    expected = np.sqrt(data * 2.0) / 2.0
    np.testing.assert_allclose(uncertainty, expected)
    assert "GAIN=2" in note
    assert "RDNOISE" not in note


def test_spectral_trace_process_reports_the_real_noise_model_when_gain_is_available():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    params["_header"] = {"GAIN": 1.5, "RDNOISE": 4.0}
    result = process.run(data, params)

    assert "ruido real" in result.summary
    assert "GAIN=1.5" in result.summary


def test_spectral_trace_process_reports_the_approximate_noise_model_without_gain():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile /= profile.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    params["_header"] = {}
    result = process.run(data, params)

    assert "ruido Poisson aproximado" in result.summary


def test_quality_map_flags_only_nonfinite_pixels_without_a_real_saturate_header():
    data = np.full((10, 10), 100.0)
    data[3, 3] = np.nan
    data[5, 5] = np.inf

    process = _get("spectroscopy.quality_map")
    params = _default_params(process)
    params["_header"] = {}
    result = process.run(data, params)

    assert result.output_data is not None
    assert result.output_data[3, 3] != 0.0
    assert result.output_data[5, 5] != 0.0
    assert result.output_data[0, 0] == 0.0  # píxel bueno real
    assert np.count_nonzero(result.output_data) == 2
    assert "2 píxel(es) marcados" in result.summary


def test_quality_map_flags_real_saturated_pixels_with_a_real_saturate_header():
    data = np.full((10, 10), 100.0)
    data[2, 2] = 900.0
    data[7, 7] = 900.0

    process = _get("spectroscopy.quality_map")
    params = _default_params(process)
    params["_header"] = {"SATURATE": 800.0}
    result = process.run(data, params)

    assert result.output_data[2, 2] != 0.0
    assert result.output_data[7, 7] != 0.0
    assert np.count_nonzero(result.output_data) == 2
    assert "SATURATE=800" in "\n".join(result.log_lines)


def test_quality_map_detects_cosmic_rays_only_when_requested():
    rng = np.random.default_rng(3)
    data = 100.0 + rng.normal(0, 1.0, (30, 30))
    data[15, 15] += 5000.0  # pico puntiagudo real, típico de un rayo cósmico

    process = _get("spectroscopy.quality_map")
    params = _default_params(process)
    params["_header"] = {}
    params["detect_cosmic_rays"] = False
    result_off = process.run(data, params)
    assert result_off.output_data[15, 15] == 0.0  # sin detección activada, no se marca

    params["detect_cosmic_rays"] = True
    result_on = process.run(data, params)
    assert result_on.output_data[15, 15] != 0.0
    assert any("COSMIC_RAY" in line for line in result_on.log_lines)


def test_build_process_registry_offers_saved_instrument_profiles_as_choices(tmp_path):
    from services.instrument_profiles import InstrumentProfile, InstrumentProfileStore

    store = InstrumentProfileStore(tmp_path / "profiles.json")
    store.save(InstrumentProfile(name="ZWO ASI294MM", gain_e_per_adu=1.2, read_noise_e=3.0))

    registry = build_process_registry(profile_store=store)
    trace_process = next(p for p in registry if p.process_id == "spectroscopy.trace")
    profile_param = next(p for p in trace_process.parameters if p.name == "instrument_profile")

    assert "ZWO ASI294MM" in profile_param.choices
    assert profile_param.default == "(usar cabecera FITS)"


def test_uncertainty_adu_falls_back_to_a_saved_instrument_profile_without_a_real_gain_header():
    from services.instrument_profiles import InstrumentProfile

    data = np.array([100.0, 400.0])
    profiles = {"ZWO ASI294MM": InstrumentProfile(name="ZWO ASI294MM", gain_e_per_adu=1.2, read_noise_e=3.0)}

    uncertainty, note = _uncertainty_adu(
        data, {"_header": {}, "instrument_profile": "ZWO ASI294MM", "_instrument_profiles": profiles}
    )

    expected = np.sqrt(data * 1.2 + 3.0**2) / 1.2
    np.testing.assert_allclose(uncertainty, expected)
    assert "ZWO ASI294MM" in note
    assert "GAIN=1.2" in note


def test_uncertainty_adu_prefers_real_header_gain_over_a_saved_profile():
    from services.instrument_profiles import InstrumentProfile

    data = np.array([100.0])
    profiles = {"ZWO ASI294MM": InstrumentProfile(name="ZWO ASI294MM", gain_e_per_adu=1.2, read_noise_e=3.0)}

    uncertainty, note = _uncertainty_adu(
        data, {"_header": {"GAIN": 2.0}, "instrument_profile": "ZWO ASI294MM", "_instrument_profiles": profiles}
    )

    expected = np.sqrt(data * 2.0) / 2.0
    np.testing.assert_allclose(uncertainty, expected)
    assert "GAIN=2" in note
    assert "perfil" not in note


def test_uncertainty_adu_ignores_the_sentinel_no_profile_choice():
    data = np.array([100.0])

    uncertainty, note = _uncertainty_adu(data, {"_header": {}, "instrument_profile": "(usar cabecera FITS)", "_instrument_profiles": {}})

    np.testing.assert_allclose(uncertainty, np.sqrt(data))
    assert note is None


def test_spectral_trace_process_reports_a_saved_instrument_profile_in_the_summary():
    from services.instrument_profiles import InstrumentProfile

    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile_shape = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile_shape /= profile_shape.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile_shape

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    params["_header"] = {}
    params["instrument_profile"] = "ZWO ASI294MM"
    params["_instrument_profiles"] = {"ZWO ASI294MM": InstrumentProfile(name="ZWO ASI294MM", gain_e_per_adu=1.2, read_noise_e=3.0)}
    result = process.run(data, params)

    assert "perfil de instrumento «ZWO ASI294MM»" in result.summary


def test_spectral_trace_process_reports_a_real_trace_overlay():
    height, width = 41, 150
    yy, _xx = np.mgrid[0:height, 0:width]
    profile_shape = np.exp(-(((yy - 20.0) ** 2)) / (2 * 2.0**2))
    profile_shape /= profile_shape.sum(axis=0, keepdims=True)
    data = 80.0 + 3000.0 * profile_shape

    process = _get("spectroscopy.trace")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 20.0)]
    result = process.run(data, params)

    overlay = result.artifacts["trace_overlay"]
    assert overlay.trace_columns.size == width
    assert overlay.trace_center_px.size == width
    np.testing.assert_allclose(overlay.trace_center_px, 20.0, atol=1.0)
    assert overlay.aperture_half_width == params["aperture_half_width"]
    assert len(overlay.sky_windows) == 2


def test_multi_aperture_process_reports_one_trace_overlay_per_aperture():
    height, width = 60, 150
    rows = np.arange(height)[:, np.newaxis]
    data = np.full((height, width), 80.0)
    for center, flux in ((15.0, 3000.0), (45.0, 5000.0)):
        profile = np.exp(-((rows - center) ** 2) / (2 * 2.0**2))
        profile /= profile.sum(axis=0, keepdims=True)
        data = data + flux * profile

    process = _get("spectroscopy.multiaperture")
    params = _default_params(process)
    params["_picked_points"] = [(0.0, 15.0), (0.0, 45.0)]
    result = process.run(data, params)

    overlays = result.artifacts["trace_overlay"]
    assert len(overlays) == 2
    assert overlays[0].label == "Apertura 1"
    assert overlays[1].label == "Apertura 2"
    np.testing.assert_allclose(overlays[0].trace_center_px, 15.0, atol=1.0)
    np.testing.assert_allclose(overlays[1].trace_center_px, 45.0, atol=1.0)


def test_extended_extraction_process_reports_one_constant_overlay_per_region():
    height, width = 80, 150
    data = np.full((height, width), 80.0)
    data[20:60, :] += 100.0

    process = _get("spectroscopy.extended_extraction")
    params = _default_params(process)
    params["bg_offset"] = 40.0
    params["_picked_points"] = [(0.0, 20.0), (0.0, 39.0)]
    result = process.run(data, params)

    overlays = result.artifacts["trace_overlay"]
    assert len(overlays) == 1
    overlay = overlays[0]
    assert overlay.trace_columns.size == width
    np.testing.assert_allclose(overlay.trace_center_px, 29.5)  # centro real de la región 20-39
    assert overlay.aperture_half_width == pytest.approx(9.5)
