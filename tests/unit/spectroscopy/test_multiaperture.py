"""Pruebas reales de `spectroscopy/multiaperture.py`: detección de picos
espaciales reales (posiciones conocidas, no solo "encuentra algo") y
extracción por lote con recuperación de flujo conocido por apertura,
incluida resiliencia real quando una apertura del lote no se puede
extraer."""
from __future__ import annotations

import numpy as np
import pytest

from astrophysics_suite.spectroscopy.multiaperture import extract_multi_aperture, find_aperture_centers


def _two_object_frame(shape=(60, 150), *, centers=(15.0, 45.0), sigma=2.0, fluxes=(4000.0, 6000.0), background=50.0, seed=5):
    rng = np.random.default_rng(seed)
    height, width = shape
    rows = np.arange(height)[:, np.newaxis]
    data = np.full(shape, background)
    for center, flux in zip(centers, fluxes):
        profile = np.exp(-((rows - center) ** 2) / (2 * sigma**2))
        profile /= profile.sum(axis=0, keepdims=True)
        data = data + flux * profile
    data = data + rng.normal(0, 2.0, shape)
    uncertainty = np.sqrt(np.clip(data, 1.0, None))
    return data.astype(np.float64), uncertainty.astype(np.float64)


def test_find_aperture_centers_recovers_known_spatial_positions():
    data, _ = _two_object_frame()
    centers = find_aperture_centers(data, min_separation_px=10.0)
    assert len(centers) == 2
    assert sorted(centers) == pytest.approx(sorted([15.0, 45.0]), abs=1.5)


def test_find_aperture_centers_returns_empty_on_flat_field():
    data = np.full((40, 40), 100.0)
    assert find_aperture_centers(data) == []


def test_find_aperture_centers_respects_max_apertures_keeping_the_brightest():
    data, _ = _two_object_frame(centers=(10.0, 30.0, 50.0), fluxes=(2000.0, 8000.0, 3000.0))
    centers = find_aperture_centers(data, min_separation_px=10.0, max_apertures=2)
    assert len(centers) == 2
    # las dos más brillantes son 30 (8000) y 50 (3000) -- 10 (2000) queda fuera
    assert sorted(centers) == pytest.approx(sorted([30.0, 50.0]), abs=1.5)


def test_extract_multi_aperture_recovers_each_apertures_known_flux():
    data, uncertainty = _two_object_frame(centers=(15.0, 45.0), fluxes=(4000.0, 6000.0))

    result = extract_multi_aperture(data, uncertainty, aperture_centers=[15.0, 45.0], optimal_extraction=False, aperture_half_width=8.0)

    assert len(result.apertures) == 2
    assert result.failures == []
    for aperture, expected_flux in zip(result.apertures, (4000.0, 6000.0)):
        assert float(np.median(aperture.spectrum.flux)) == pytest.approx(expected_flux, rel=0.1)


def test_extract_multi_aperture_auto_detects_when_no_centers_given():
    data, uncertainty = _two_object_frame(centers=(15.0, 45.0), fluxes=(4000.0, 6000.0))

    result = extract_multi_aperture(data, uncertainty, optimal_extraction=False)

    assert len(result.apertures) == 2
    assert [a.aperture_id for a in result.apertures] == [1, 2]
    assert [a.initial_center_px for a in result.apertures] == pytest.approx([15.0, 45.0], abs=1.5)


def test_extract_multi_aperture_reports_out_of_bounds_center_as_a_failure_without_stopping_the_batch():
    data, uncertainty = _two_object_frame(centers=(15.0, 45.0), fluxes=(4000.0, 6000.0))

    result = extract_multi_aperture(data, uncertainty, aperture_centers=[15.0, 999.0, 45.0], optimal_extraction=False)

    assert len(result.apertures) == 2
    assert len(result.failures) == 1
    failure = result.failures[0]
    assert failure.aperture_id == 2
    assert failure.initial_center_px == 999.0
    assert "imagen" in failure.reason
    # las aperturas válidas conservan su propio aperture_id (1 y 3), no se renumeran
    assert [a.aperture_id for a in result.apertures] == [1, 3]


def test_extract_multi_aperture_rejects_mismatched_shapes():
    data, uncertainty = _two_object_frame()
    with pytest.raises(ValueError):
        extract_multi_aperture(data, uncertainty[:-1, :], aperture_centers=[15.0])
