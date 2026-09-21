from __future__ import annotations

from astrophysics_suite.artifacts.morphology_screen import artifact_checks_for, classify_morphology, quality_check_for
from astrophysics_suite.core.enums import ArtifactKind, MorphologyClass, QualityLevel
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.detection import Detection, MorphologySummary, SkyPosition


def _detection(*, area_px, elongation, compactness, peak_snr) -> Detection:
    return Detection.create(
        detection_id="DET-TEST",
        observation_id="OBS-TEST",
        position=SkyPosition(x_px=10.0, y_px=10.0),
        morphology=MorphologySummary(morphology_class=MorphologyClass.POINT_SOURCE, area_px=area_px, elongation=elongation, compactness=compactness),
        bands=("HA",),
        peak_snr=peak_snr,
        method="test",
        provenance=Provenance.now(pipeline_version="test", engine="test", engine_version="1.0"),
    )


def test_extreme_elongation_is_rejected_as_processing_artifact():
    d = _detection(area_px=50.0, elongation=9.0, compactness=0.3, peak_snr=10.0)
    state, _ = classify_morphology(d)
    assert state == "ARTIFACT_REJECTED"
    checks = artifact_checks_for(d)
    assert len(checks) == 1
    assert checks[0].kind is ArtifactKind.PROCESSING_ARTIFACT
    assert checks[0].flagged is True
    assert quality_check_for(d).level is QualityLevel.FAIL


def test_extremely_compact_source_is_rejected_as_other_artifact():
    d = _detection(area_px=1.0, elongation=1.2, compactness=0.3, peak_snr=10.0)
    state, _ = classify_morphology(d)
    assert state == "ARTIFACT_REJECTED"
    checks = artifact_checks_for(d)
    assert checks[0].kind is ArtifactKind.OTHER


def test_low_snr_is_quality_limited_not_artifact():
    d = _detection(area_px=50.0, elongation=1.2, compactness=0.3, peak_snr=2.0)
    state, _ = classify_morphology(d)
    assert state == "QUALITY_LIMITED"
    assert artifact_checks_for(d) == ()  # QUALITY_LIMITED no es lo mismo que "es un artefacto"
    assert quality_check_for(d).level is QualityLevel.WARNING


def test_clean_point_source_passes():
    d = _detection(area_px=50.0, elongation=1.3, compactness=0.4, peak_snr=12.0)
    state, _ = classify_morphology(d)
    assert state == "SCIENCE_CANDIDATE"
    assert artifact_checks_for(d) == ()
    assert quality_check_for(d).level is QualityLevel.PASS


def test_inconclusive_morphology_is_review_not_rejection():
    d = _detection(area_px=50.0, elongation=4.0, compactness=0.1, peak_snr=10.0)
    state, _ = classify_morphology(d)
    assert state == "REVIEW"
    assert artifact_checks_for(d) == ()
