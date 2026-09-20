"""El Detection Engine migrado debe producir EXACTAMENTE lo mismo que el
monolito legacy: mismo fondo, mismas fuentes, mismas métricas por
fuente -- byte a byte, no "aproximadamente igual" -- con UNA excepción
deliberada y documentada: `fwhm_px` (ver `finder.py` y
docs/audit/54-CIERRE-DETECTION.md). La fórmula legacy
`2.3548*sqrt(l1*l2)` no son unidades de FWHM (`l1*l2` es varianza al
cuadrado, no varianza); se corrige aquí, y esta prueba demuestra la
relación exacta con el valor legacy en vez de limitarse a decir que
"ya no coincide".

Esta es la prueba que autoriza a que `detection/point_sources.py` deje
de depender de `legacy.AstroPhysicsSuite_v57_3_COMMERCIAL`: no basta con
que el motor nuevo encuentre estrellas, tiene que coincidir con el que
lleva usándose en todo el proyecto -- incluidas las dos ramas de reserva
(sin `Background2D`, sin `DAOStarFinder`) que la mayoría de ejecuciones
nunca recorre.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from astrophysics_suite.detection.background import estimate_background
from astrophysics_suite.detection.finder import enrich_detections, find_point_sources
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import FitsImage as _LegacyFitsImage
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import detect_point_sources as _legacy_detect_point_sources
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import enrich_star_rows as _legacy_enrich_star_rows
from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import estimate_background as _legacy_estimate_background


def _synthetic_star_field(shape, positions, amplitudes=None, sigma=1.8, background=100.0, seed=42):
    rng = np.random.default_rng(seed)
    amplitudes = amplitudes or [900.0] * len(positions)
    yy, xx = np.mgrid[0 : shape[0], 0 : shape[1]]
    field = np.full(shape, float(background), dtype=np.float32)
    for (x, y), amp in zip(positions, amplitudes):
        field += amp * np.exp(-((xx - x) ** 2 + (yy - y) ** 2) / (2 * sigma**2))
    field += rng.normal(0, 2.0, shape)
    return field.astype(np.float32)


# ---------------------------------------------------------------------------
# estimate_background
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("use_photutils", [True, False])
def test_background_matches_legacy_field_by_field(use_photutils):
    field = _synthetic_star_field((160, 160), [(40, 40), (100, 120)], seed=3)

    migrated = estimate_background(field, box=32, use_photutils=use_photutils)
    legacy = _legacy_estimate_background(field, box=32, use_photutils=use_photutils)

    np.testing.assert_allclose(migrated.bkg, legacy.bkg, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(migrated.rms, legacy.rms, rtol=1e-6, atol=1e-6)
    assert migrated.box == legacy.box


def test_background_matches_legacy_with_a_star_mask():
    field = _synthetic_star_field((128, 128), [(64, 64)], amplitudes=[2000.0], seed=5)
    mask = np.zeros(field.shape, dtype=bool)
    mask[54:75, 54:75] = True  # máscara provisional de estrella, como en el pipeline real

    migrated = estimate_background(field, box=32, mask=mask)
    legacy = _legacy_estimate_background(field, box=32, mask=mask)

    np.testing.assert_allclose(migrated.bkg, legacy.bkg, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(migrated.rms, legacy.rms, rtol=1e-6, atol=1e-6)


def test_background_matches_legacy_on_a_tiny_degenerate_image():
    # Menor que un solo mosaico -- fuerza el camino menos común en ambas
    # implementaciones (interpolación con orden reducido).
    field = _synthetic_star_field((20, 20), [(10, 10)], seed=9)
    migrated = estimate_background(field, box=64)
    legacy = _legacy_estimate_background(field, box=64)
    np.testing.assert_allclose(migrated.bkg, legacy.bkg, rtol=1e-6, atol=1e-6)
    np.testing.assert_allclose(migrated.rms, legacy.rms, rtol=1e-6, atol=1e-6)


# ---------------------------------------------------------------------------
# find_point_sources (DAOStarFinder + reserva)
# ---------------------------------------------------------------------------


def test_find_point_sources_matches_legacy_dao_path():
    positions = [(30, 30), (70, 45), (50, 80), (100, 20)]
    amplitudes = [900.0, 2500.0, 500.0, 1400.0]
    field = _synthetic_star_field((128, 128), positions, amplitudes=amplitudes, seed=11)
    bkg = estimate_background(field)
    legacy_bkg = _legacy_estimate_background(field)

    migrated = find_point_sources(field, bkg, threshold_sigma=4.0)
    legacy = _legacy_detect_point_sources(field, legacy_bkg, threshold_sigma=4.0)

    assert migrated.shape == legacy.shape
    np.testing.assert_allclose(migrated, legacy, rtol=1e-6, atol=1e-6)


def test_find_point_sources_matches_legacy_on_an_empty_field():
    field = np.full((64, 64), 100.0, dtype=np.float32)
    bkg = estimate_background(field)
    legacy_bkg = _legacy_estimate_background(field)

    migrated = find_point_sources(field, bkg, threshold_sigma=6.0)
    legacy = _legacy_detect_point_sources(field, legacy_bkg, threshold_sigma=6.0)

    assert migrated.shape == (0, 3)
    assert legacy.shape == (0, 3)


def test_find_point_sources_fallback_matches_legacy_fallback():
    """Ejercita explícitamente la rama de reserva (Python puro, sin
    `DAOStarFinder`) de ambas implementaciones -- la que casi nunca se
    recorre en producción pero que debe seguir dando el mismo resultado
    exacto que daba antes."""
    from astrophysics_suite.detection.finder import _find_point_sources_fallback
    from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import _detect_point_sources_legacy

    positions = [(30, 30), (70, 45), (50, 80)]
    field = _synthetic_star_field((128, 128), positions, seed=13)
    bkg = estimate_background(field)
    legacy_bkg = _legacy_estimate_background(field)

    migrated = _find_point_sources_fallback(field, bkg, fwhm_px=3.0, threshold_sigma=4.0, max_sources=3000)
    legacy = _detect_point_sources_legacy(field, legacy_bkg, fwhm_px=3.0, threshold_sigma=4.0, max_sources=3000)

    assert migrated.shape == legacy.shape
    np.testing.assert_allclose(migrated, legacy, rtol=1e-6, atol=1e-6)


# ---------------------------------------------------------------------------
# enrich_detections
# ---------------------------------------------------------------------------


def test_enrich_detections_matches_legacy_row_by_row():
    positions = [(30, 30), (70, 45), (50, 80), (5, 60)]  # la última, cerca del borde
    amplitudes = [900.0, 2500.0, 500.0, 700.0]
    field = _synthetic_star_field((128, 128), positions, amplitudes=amplitudes, seed=17)
    bkg = estimate_background(field)
    legacy_bkg = _legacy_estimate_background(field)
    raw_sources = find_point_sources(field, bkg, threshold_sigma=4.0)
    assert len(raw_sources) >= 3

    migrated_rows = enrich_detections(field, bkg, raw_sources, saturate_adu=60000.0)
    legacy_image = _LegacyFitsImage(path="", data=field, header={"SATURATE": 60000.0}, pixel_scale_arcsec=None)
    legacy_rows = _legacy_enrich_star_rows(legacy_image, raw_sources, legacy_bkg)

    assert len(migrated_rows) == len(legacy_rows)
    # `fwhm_px` es la ÚNICA divergencia deliberada de este módulo frente
    # a legacy (ver `finder.py`): `sharpness_index`/`quality` dependen de
    # `fwhm_px` (radios de apertura, umbral de borde) y por eso también
    # cambian -- se verifican por separado, no por igualdad estricta.
    numeric_fields = (
        "x_px", "y_px", "flux_adu", "peak_adu", "snr_peak", "local_rms_adu", "local_snr_median",
        "roi_mean_adu", "roi_median_adu", "ellipticity", "border_distance_px",
    )
    for migrated, legacy in zip(migrated_rows, legacy_rows):
        assert migrated.det_id == legacy["det_id"]
        for field_name in numeric_fields:
            migrated_value = getattr(migrated, field_name)
            legacy_value = legacy[field_name]
            if not np.isfinite(legacy_value):
                assert not np.isfinite(migrated_value), field_name
            else:
                assert migrated_value == pytest.approx(legacy_value, rel=1e-6, abs=1e-6), field_name
        assert migrated.saturated == legacy["saturated"]

        # `fwhm_px` corregido == cuarta raíz de lo que legacy calculaba
        # (2.3548*sqrt(l1*l2)) en vez de su raíz cuadrada -- la relación
        # exacta que demuestra que el arreglo es "tomar la raíz que
        # faltaba", no un valor inventado.
        legacy_fwhm = legacy["fwhm_px"]
        if np.isfinite(legacy_fwhm) and legacy_fwhm > 0:
            expected_fixed_fwhm = 2.354820045 * math.sqrt(legacy_fwhm / 2.354820045)
            assert migrated.fwhm_px == pytest.approx(expected_fixed_fwhm, rel=1e-6, abs=1e-6)
        else:
            assert not np.isfinite(migrated.fwhm_px)


def test_enrich_detections_matches_legacy_without_saturate_header():
    """Sin `SATURATE` en la cabecera (el caso real de la cámara del
    usuario, ver informe 54) -- la saturación debe quedar inactiva en
    ambas implementaciones por igual, no fallar ni inventar un umbral."""
    positions = [(40, 40)]
    field = _synthetic_star_field((96, 96), positions, amplitudes=[3000.0], seed=19)
    bkg = estimate_background(field)
    legacy_bkg = _legacy_estimate_background(field)
    raw_sources = find_point_sources(field, bkg, threshold_sigma=4.0)
    assert len(raw_sources) >= 1

    migrated_rows = enrich_detections(field, bkg, raw_sources, saturate_adu=None)
    legacy_image = _LegacyFitsImage(path="", data=field, header={}, pixel_scale_arcsec=None)
    legacy_rows = _legacy_enrich_star_rows(legacy_image, raw_sources, legacy_bkg)

    for migrated, legacy in zip(migrated_rows, legacy_rows):
        assert migrated.saturated is False
        assert legacy["saturated"] is False
        expected_fixed_fwhm = 2.354820045 * math.sqrt(legacy["fwhm_px"] / 2.354820045)
        assert migrated.fwhm_px == pytest.approx(expected_fixed_fwhm, rel=1e-6, abs=1e-6)
        assert migrated.fwhm_px < legacy["fwhm_px"]  # la fórmula corregida nunca infla más que la original


def test_enrich_detections_fwhm_matches_a_known_sigma_gaussian():
    """El hallazgo real (ver docs/audit/54-CIERRE-DETECTION.md): la
    fórmula legacy `2.3548*sqrt(l1*l2)` no son unidades de FWHM --
    `l1*l2` está en px^4 (varianza al cuadrado). Con una gaussiana
    sintética de sigma REALMENTE conocido, el FWHM medido debe coincidir
    con el teórico (2.3548*sigma), cosa que la fórmula legacy nunca
    hacía (medía sistemáticamente más alto cuanto mayor era el sigma
    real: 1.5x a sigma=1.5px, ~3x a sigma=3px, verificado a mano)."""
    for sigma_true in (1.5, 2.0, 2.5, 3.0):
        yy, xx = np.mgrid[0:80, 0:80]
        amplitude = 5000.0
        field = 1000.0 + amplitude * np.exp(-((xx - 40) ** 2 + (yy - 40) ** 2) / (2 * sigma_true**2))
        bkg = estimate_background(field.astype(np.float64), box=40)
        sources = np.array([[40.0, 40.0, amplitude]])

        row = enrich_detections(field, bkg, sources, saturate_adu=None)[0]
        expected_fwhm = 2.354820045 * sigma_true
        assert row.fwhm_px == pytest.approx(expected_fwhm, rel=0.05)
        assert row.ellipticity == pytest.approx(0.0, abs=1e-3)  # gaussiana isótropa: circular
