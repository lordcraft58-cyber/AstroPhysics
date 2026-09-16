"""Los adaptadores de proceso son numpy puro -- comprobables sin Qt. No
deben reimplementar ninguna matemática, solo traducir parámetros/resultados;
estas pruebas confirman que la traducción en sí es correcta."""
from __future__ import annotations

import math

import numpy as np
import pytest

from qt_app.processes.registry import build_process_registry


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
    registry = build_process_registry()
    categories = {p.category for p in registry}
    assert categories == {"Reducción CCD", "Utilidades de imagen", "Fotometría", "Espectroscopía", "Astrometría"}


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
    assert result.table.columns == ("star", "x", "y", "ra", "dec", "instrumental_mag", "catalog_mag", "separation")
    assert len(result.table.rows) == 2
    assert result.table.rows[0][0] == 1  # numeración de estrella desde 1


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


def test_spectral_trace_process_requires_one_point_and_extracts_strip():
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

    assert result.output_data is not None
    assert result.output_data.shape == (20, width)
    assert "Traza extraída" in result.summary


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
