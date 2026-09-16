from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrophysics_suite.core.enums import (
    ArtifactKind,
    IdentificationState,
    MorphologyClass,
    QualityLevel,
    ReviewState,
    ValueKind,
)
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import (
    AIAssessment,
    ArtifactCheck,
    Candidate,
    CatalogMatch,
    CatalogQuery,
    QualityCheckItem,
    QualitySummary,
)
from astrophysics_suite.models.detection import MorphologySummary, SkyPosition


def _sample_candidate() -> Candidate:
    return Candidate.create(
        candidate_id="CAND-0001",
        observation_id="OBS-0001",
        detection_id="DET-0001",
        position=SkyPosition(x_px=128.0, y_px=64.0, ra_deg=312.75, dec_deg=30.7, position_error_arcsec=0.4),
        morphology=MorphologySummary(morphology_class=MorphologyClass.EXTENDED, area_px=340.0, elongation=1.8, compactness=0.3),
        size=Quantity(value=12.0, error=1.0, unit="arcsec", kind=ValueKind.OBSERVED, method="isophote_fit"),
        flux={"HA": Quantity(value=1200.0, error=50.0, unit="ADU", kind=ValueKind.OBSERVED, method="aperture_photometry")},
        snr=Quantity(value=8.4, error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="peak_over_rms"),
        bands=("HA", "OIII"),
        catalog_matches=(),
        catalog_non_matches=(CatalogQuery(catalog="Gaia DR3", radius_arcsec=3.0, reason="sin fuente puntual coincidente"),),
        artifact_checks=(ArtifactCheck(kind=ArtifactKind.COSMIC_RAY, flagged=False),),
        ai_evidence=(
            AIAssessment(
                model_name="AstroVision",
                model_version="2026.1",
                trained_on="real",
                novelty_score=Quantity(value=0.82, error=None, unit="dimensionless", kind=ValueKind.OBSERVED, method="embedding_distance"),
            ),
        ),
        quality=QualitySummary(overall_level=QualityLevel.PASS, checks=(QualityCheckItem(name="wcs", level=QualityLevel.PASS),)),
        provenance=Provenance.now(pipeline_version="0.4.0-dev", engine="DiscoveryEngine", engine_version="1.0"),
        identification_state=IdentificationState.UNMATCHED,
    )


def test_candidate_roundtrip():
    candidate = _sample_candidate()
    restored = Candidate.from_dict(candidate.to_dict())
    assert restored == candidate
    assert restored.identification_state is IdentificationState.UNMATCHED
    assert restored.ai_evidence[0].trained_on == "real"


def test_candidate_starts_pending_with_no_review_history():
    candidate = _sample_candidate()
    assert candidate.review_state is ReviewState.PENDING
    assert candidate.review_notes == ()


def test_candidate_is_frozen():
    candidate = _sample_candidate()
    with pytest.raises(AttributeError):
        candidate.review_state = ReviewState.KEPT  # type: ignore[misc]


def test_mark_reviewed_returns_new_instance_and_preserves_history():
    original = _sample_candidate()
    reviewed_at = datetime(2026, 9, 20, tzinfo=timezone.utc)

    kept = original.mark_reviewed(new_state=ReviewState.KEPT, author="dra.astronoma", note="Morfología inusual, se conserva para seguimiento.", reviewed_at=reviewed_at)

    # El original NO cambia -- inmutabilidad real, no una ilusión de API.
    assert original.review_state is ReviewState.PENDING
    assert original.review_notes == ()

    assert kept.review_state is ReviewState.KEPT
    assert len(kept.review_notes) == 1
    assert kept.review_notes[0].previous_state is ReviewState.PENDING
    assert kept.review_notes[0].new_state is ReviewState.KEPT
    assert kept.review_notes[0].author == "dra.astronoma"

    # Una segunda revisión se acumula, no sobreescribe.
    flagged = kept.mark_reviewed(new_state=ReviewState.FLAGGED, author="otro.revisor", note="Requiere segunda opinión.", reviewed_at=reviewed_at)
    assert len(flagged.review_notes) == 2
    assert flagged.review_notes[0].new_state is ReviewState.KEPT
    assert flagged.review_notes[1].new_state is ReviewState.FLAGGED
    assert flagged.review_notes[1].previous_state is ReviewState.KEPT
    # kept, un paso atrás en la cadena, sigue intacto.
    assert len(kept.review_notes) == 1


def test_mark_reviewed_rejects_returning_to_pending():
    candidate = _sample_candidate()
    with pytest.raises(ValueError):
        candidate.mark_reviewed(new_state=ReviewState.PENDING, author="x", note="", reviewed_at=datetime.now(timezone.utc))


def test_candidate_never_declares_discovery():
    """Ningún estado de Candidate significa "descubrimiento confirmado" --
    ni siquiera DISCOVERY_REVIEW, que pide explícitamente revisión humana."""
    candidate = _sample_candidate()
    discovery_like_values = {s.value for s in IdentificationState}
    assert "DISCOVERY_CONFIRMED" not in discovery_like_values
    assert "NEW_OBJECT" not in discovery_like_values
