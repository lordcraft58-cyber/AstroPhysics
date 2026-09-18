"""Prueba end-to-end (no simulada) de photometry/quality.py: FITS
sintético real con una fuente inyectada, medida con measure_source_quality
heredado y traducida a CharacterizationResult."""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.io.fits_loader import load_image
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition
from astrophysics_suite.photometry.quality import characterize_point_source
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _write_minimal_fits_2d


def _detection_at(x, y) -> Detection:
    return Detection.create(
        detection_id="DET-0001",
        observation_id="OBS-0001",
        position=SkyPosition(x_px=x, y_px=y),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=10.0, elongation=1.0, compactness=0.5),
        bands=("HA",),
        peak_snr=10.0,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )


def _star_field(shape, x, y, amplitude=900.0, sigma=2.2, background=100.0):
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = background + amplitude * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    return field.astype(np.float32)


def test_characterize_point_source_measures_real_fwhm(tmp_path):
    field = _star_field((64, 64), 32, 32, sigma=2.2)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(32, 32))

    assert result.fwhm is not None
    assert result.fwhm.kind is ValueKind.OBSERVED
    # sigma=2.2 -> FWHM teórico = 2.3548*sigma ~= 5.18 px; tolerancia amplia
    # porque la medida heredada usa una caja recortada y ruido de fondo cero.
    assert 3.0 < result.fwhm.value < 8.0
    assert result.elongation is not None
    # Fuente sintética perfectamente circular: elongación debe ser ~1.0.
    assert 0.9 < result.elongation.value < 1.3


def test_characterize_point_source_reports_not_available_when_cutout_too_small(tmp_path):
    field = _star_field((64, 64), 32, 32)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    # cutout_size=3 -> recorte de 3x3, por debajo del mínimo de 5x5 que
    # exige measure_source_quality ("Cutout demasiado pequeño").
    result = characterize_point_source(loaded, _detection_at(32, 32), cutout_size=3)

    assert result.fwhm is None
    assert "quality_measurement" in result.extra
    assert not result.extra["quality_measurement"].is_available


def test_characterize_point_source_propagates_pixel_measurements_needed_by_artifact_screen(tmp_path):
    # artifact_screen.py consume snr_local, peak_adu, background_adu,
    # noise_adu, saturated, isolated y n_peaks_in_stamp directamente de
    # CharacterizationResult.extra -- antes de cacac21 se medían y se
    # descartaban aquí, obligando a remedirlos por una segunda vía.
    field = _star_field((64, 64), 32, 32, amplitude=900.0, background=100.0)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(32, 32))

    for key in ("sharpness", "snr_local", "peak_adu", "background_adu", "noise_adu", "n_peaks_in_stamp"):
        assert key in result.extra, key
        assert result.extra[key].is_available, key

    # Fuente aislada, sin saturar: ambos booleanos deben quedar en 0.0 (False),
    # nunca ausentes.
    assert result.extra["saturated"].value == 0.0
    assert result.extra["isolated"].value == 1.0
    assert result.extra["peak_adu"].value > result.extra["background_adu"].value


def test_characterize_point_source_flags_saturation_as_a_real_measurement(tmp_path):
    # amplitude muy por encima del rango típico de una cámara de 16 bits:
    # measure_source_quality debe detectar el pico como saturado de verdad,
    # no como una fuente brillante normal.
    field = _star_field((64, 64), 32, 32, amplitude=70000.0, background=100.0)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(32, 32), saturation_level=65535.0)

    assert result.extra["saturated"].value == 1.0
    assert result.extra["saturated"].unit == "boolean"


def _gaussian_field_with_known_flux(shape, x0, y0, *, true_flux, sigma, background):
    """A diferencia de `_star_field` (parametrizada por amplitud de pico),
    esta parametriza por flujo TOTAL conocido -- misma convención que
    `tests/unit/photometry/test_aperture.py::_isolated_gaussian_star`, para
    poder comprobar que `characterize_point_source` recupera un flujo real,
    no solo que produce *algún* número."""
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    amplitude = true_flux / (2 * math.pi * sigma**2)
    field = background + amplitude * np.exp(-(((xx - x0) ** 2 + (yy - y0) ** 2)) / (2 * sigma**2))
    return field.astype(np.float32)


def test_characterize_point_source_recovers_a_known_injected_flux_by_real_aperture_photometry(tmp_path):
    # Campo grande para que la apertura (3x FWHM) y su anillo de cielo
    # (hasta 9x FWHM) quepan enteros lejos del borde -- si no, la
    # estimación de cielo se contaminaría con píxeles fuera de imagen.
    true_flux = 500_000.0
    sigma = 2.5
    field = _gaussian_field_with_known_flux((150, 150), 75, 75, true_flux=true_flux, sigma=sigma, background=200.0)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(75, 75))

    assert result.fwhm is not None
    assert "HA" in result.band_flux
    flux = result.band_flux["HA"]
    # radio = 3x FWHM ~= 7x sigma -> por debajo del 1e-10 del flujo total de
    # una gaussiana queda fuera de la apertura (Howell, cap. 5): tolerancia
    # del 3% cubre además la incertidumbre en el propio FWHM medido.
    assert flux.value == pytest.approx(true_flux, rel=0.03)
    assert flux.error is not None and flux.error > 0.0
    assert flux.unit == "adu"
    assert flux.method == "aperture_photometry"
    assert flux.kind is ValueKind.OBSERVED
    assert flux.notes and "apertura" in flux.notes[0]


def test_characterize_point_source_leaves_band_flux_empty_when_fwhm_is_not_available(tmp_path):
    # Mismo escenario que el test de NOT_AVAILABLE de arriba (cutout
    # demasiado pequeño): sin FWHM medida no hay con qué dimensionar una
    # apertura con criterio, así que band_flux debe quedar vacío -- nunca
    # un flujo inventado con un radio arbitrario.
    field = _star_field((64, 64), 32, 32)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(32, 32), cutout_size=3)

    assert result.fwhm is None
    assert result.band_flux == {}


def test_characterize_point_source_still_measures_a_real_partial_aperture_near_the_edge(tmp_path):
    # Fuente cerca del borde: `aperture_photometry` recorta la apertura a
    # la imagen real en vez de rechazar la medida -- menos píxeles
    # efectivos, pero un flujo real, no None.
    field = _star_field((30, 30), 2, 2, sigma=2.2)
    path = tmp_path / "field_HA.fits"
    _write_minimal_fits_2d(path, field)
    loaded = load_image(str(path), band="HA")

    result = characterize_point_source(loaded, _detection_at(2, 2))

    assert "HA" in result.band_flux
    flux = result.band_flux["HA"]
    assert flux.value > 0.0
    assert "efectivos" in flux.notes[0]


def test_measure_aperture_flux_returns_none_for_a_source_entirely_outside_the_image():
    from astrophysics_suite.photometry.quality import _measure_aperture_flux

    data = np.full((30, 30), 100.0, dtype=np.float32)

    assert _measure_aperture_flux(data, x_px=1000.0, y_px=1000.0, fwhm_px=5.0) is None
