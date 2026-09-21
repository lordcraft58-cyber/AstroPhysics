from __future__ import annotations

from astrophysics_suite.artifacts.artifact_screen import (
    FieldStatistics,
    compute_field_statistics,
    screen_detection,
)
from astrophysics_suite.core.enums import ArtifactKind, ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import Detection, MorphologyClass, MorphologySummary, SkyPosition

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")


def _q(value: float, unit: str = "dimensionless") -> Quantity:
    return Quantity(value=value, error=None, unit=unit, kind=ValueKind.OBSERVED, method="test")


def _detection(*, snr: float = 20.0) -> Detection:
    return Detection.create(
        detection_id="D0", observation_id="O",
        position=SkyPosition(x_px=10.0, y_px=10.0, ra_deg=10.0, dec_deg=41.0),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=9.0, elongation=1.1, compactness=0.6),
        bands=("L",), peak_snr=snr, method="test", provenance=_PROV,
    )


def _characterization(*, fwhm=3.5, elongation=1.1, extra: dict[str, Quantity] | None = None) -> CharacterizationResult:
    return CharacterizationResult.create(
        detection_id="D0",
        position=SkyPosition(x_px=10.0, y_px=10.0, ra_deg=10.0, dec_deg=41.0),
        provenance=_PROV,
        fwhm=_q(fwhm, "px") if fwhm is not None else None,
        elongation=_q(elongation) if elongation is not None else None,
        extra=extra or {},
    )


_CLEAN_EXTRA = {
    "snr_local": _q(15.0),
    "saturated": _q(0.0, "boolean"),
    "n_peaks_in_stamp": _q(1.0, "count"),
}

_FIELD_WITH_REFERENCE = FieldStatistics(n_sources=20, median_fwhm_px=3.5, fwhm_scatter_px=0.3)
_FIELD_WITHOUT_REFERENCE = FieldStatistics(n_sources=2, median_fwhm_px=None, fwhm_scatter_px=None)


def test_clean_point_source_is_not_rejected():
    result = screen_detection(_detection(), _characterization(extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE)
    assert not result.rejected
    assert result.flagged_kinds == ()
    assert "Ninguna comprobación" in result.reason
    # Todas las 12 categorías de ArtifactKind deben aparecer, disponibles o no.
    assert {c.kind for c in result.checks} == set(ArtifactKind)


def test_saturated_source_is_flagged_and_rejects():
    extra = dict(_CLEAN_EXTRA, saturated=_q(1.0, "boolean"))
    result = screen_detection(_detection(), _characterization(extra=extra), _FIELD_WITH_REFERENCE)
    assert result.rejected
    assert ArtifactKind.SATURATION in result.flagged_kinds


def test_missing_saturation_measurement_is_reported_not_available_not_clean():
    extra = {k: v for k, v in _CLEAN_EXTRA.items() if k != "saturated"}
    result = screen_detection(_detection(), _characterization(extra=extra), _FIELD_WITH_REFERENCE)
    sat_check = next(c for c in result.checks if c.kind is ArtifactKind.SATURATION)
    assert not sat_check.flagged
    assert not sat_check.confidence.is_available


def test_low_snr_is_flagged_as_noise():
    extra = dict(_CLEAN_EXTRA, snr_local=_q(1.0))
    result = screen_detection(_detection(snr=1.0), _characterization(extra=extra), _FIELD_WITH_REFERENCE, min_snr=3.0)
    assert result.rejected
    assert ArtifactKind.NOISE in result.flagged_kinds


def test_extreme_elongation_is_flagged_as_trail():
    result = screen_detection(
        _detection(), _characterization(elongation=6.0, extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE, trail_elongation=4.0,
    )
    assert result.rejected
    assert ArtifactKind.SATELLITE_OR_AIRPLANE_TRAIL in result.flagged_kinds


def test_normal_elongation_does_not_flag_trail():
    result = screen_detection(_detection(), _characterization(elongation=1.1, extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE)
    assert ArtifactKind.SATELLITE_OR_AIRPLANE_TRAIL not in result.flagged_kinds


def test_subpixel_fwhm_is_flagged_as_hot_pixel():
    result = screen_detection(
        _detection(), _characterization(fwhm=0.8, extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE, hot_pixel_fwhm_px=1.2,
    )
    assert result.rejected
    assert ArtifactKind.HOT_PIXEL in result.flagged_kinds


def test_fwhm_much_narrower_than_field_psf_is_flagged_as_cosmic_ray():
    # Campo con PSF de referencia 3.5 px; esta fuente mide 1.5 px (0.43x) --
    # más afilada que la PSF real, pero por encima del umbral de hot pixel.
    result = screen_detection(
        _detection(), _characterization(fwhm=1.5, extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE,
        cosmic_ray_fwhm_ratio=0.6, hot_pixel_fwhm_px=1.2,
    )
    assert result.rejected
    assert ArtifactKind.COSMIC_RAY in result.flagged_kinds
    assert ArtifactKind.HOT_PIXEL not in result.flagged_kinds


def test_fwhm_much_wider_than_field_psf_is_flagged_as_psf_defect():
    result = screen_detection(
        _detection(), _characterization(fwhm=8.0, extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE, psf_defect_fwhm_ratio=2.0,
    )
    assert result.rejected
    assert ArtifactKind.PSF_DEFECT in result.flagged_kinds


def test_cosmic_ray_and_psf_defect_need_a_field_reference():
    result = screen_detection(_detection(), _characterization(fwhm=1.0, extra=_CLEAN_EXTRA), _FIELD_WITHOUT_REFERENCE)
    cosmic_check = next(c for c in result.checks if c.kind is ArtifactKind.COSMIC_RAY)
    defect_check = next(c for c in result.checks if c.kind is ArtifactKind.PSF_DEFECT)
    assert not cosmic_check.confidence.is_available
    assert not defect_check.confidence.is_available


def test_registration_error_is_not_available_without_multi_epoch_data():
    result = screen_detection(_detection(), _characterization(extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE)
    check = next(c for c in result.checks if c.kind is ArtifactKind.REGISTRATION_ERROR)
    assert not check.confidence.is_available


def test_registration_error_flags_scatter_incompatible_with_known_rms():
    result = screen_detection(
        _detection(), _characterization(extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE,
        position_scatter_arcsec=5.0, registration_rms_arcsec=0.3,
    )
    assert result.rejected
    assert ArtifactKind.REGISTRATION_ERROR in result.flagged_kinds


def test_registration_error_does_not_flag_scatter_compatible_with_known_rms():
    result = screen_detection(
        _detection(), _characterization(extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE,
        position_scatter_arcsec=0.2, registration_rms_arcsec=0.3,
    )
    assert ArtifactKind.REGISTRATION_ERROR not in result.flagged_kinds


def test_categories_without_a_validated_criterion_are_always_not_available():
    result = screen_detection(_detection(), _characterization(extra=_CLEAN_EXTRA), _FIELD_WITH_REFERENCE)
    for kind in (
        ArtifactKind.REFLECTION, ArtifactKind.DONUT, ArtifactKind.GRADIENT,
        ArtifactKind.STACKING_RESIDUAL, ArtifactKind.PROCESSING_ARTIFACT,
    ):
        check = next(c for c in result.checks if c.kind is kind)
        assert not check.confidence.is_available
        assert not check.flagged


def test_blended_source_is_noted_under_other_but_never_flagged():
    # n_peaks_in_stamp > 1 es información útil (fotometría contaminada),
    # pero no es en sí mismo un criterio de rechazo: no se puede saber QUÉ es.
    extra = dict(_CLEAN_EXTRA, n_peaks_in_stamp=_q(3.0, "count"))
    result = screen_detection(_detection(), _characterization(extra=extra), _FIELD_WITH_REFERENCE)
    other_check = next(c for c in result.checks if c.kind is ArtifactKind.OTHER)
    assert not other_check.flagged
    assert "mezclada" in other_check.notes
    assert not result.rejected


def test_compute_field_statistics_needs_a_minimum_population():
    few = [_characterization(fwhm=3.0), _characterization(fwhm=3.5)]
    stats = compute_field_statistics(few, min_sources=5)
    assert stats.n_sources == 2
    assert not stats.has_psf_reference
    assert stats.median_fwhm_px is None


def test_compute_field_statistics_measures_real_median_and_scatter():
    values = [3.0, 3.2, 3.4, 3.6, 3.8, 10.0]  # el 10.0 es un outlier real
    chars = [_characterization(fwhm=v) for v in values]
    stats = compute_field_statistics(chars, min_sources=5)
    assert stats.n_sources == 6
    assert stats.has_psf_reference
    assert 3.3 < stats.median_fwhm_px < 3.7
    # MAD escalado: robusto frente al outlier de 10.0, no se dispara.
    assert stats.fwhm_scatter_px < 1.0
