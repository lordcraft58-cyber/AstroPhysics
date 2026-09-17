"""Tests reales de evidence/chain_builder.py -- el último paso antes de
Candidate. La regla central a proteger: independencia por MOTORES
DISTINTOS, nunca por número de piezas, y `priority_index` siempre
desmontable en `items`."""
from __future__ import annotations

from astrophysics_suite.anomaly.vector import build_anomaly_vector
from astrophysics_suite.core.enums import ArtifactKind, ValueKind
from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.evidence.chain_builder import build_evidence_chain
from astrophysics_suite.models.candidate import ArtifactCheck, CatalogMatch, CatalogQuery
from astrophysics_suite.models.characterization import CharacterizationResult
from astrophysics_suite.models.detection import SkyPosition
from astrophysics_suite.models.evidence import EvidenceChain
from astrophysics_suite.models.temporal import MotionEvidence, TemporalEvidence
from astrophysics_suite.physics.constraints import evaluate_consistency
from astrophysics_suite.physics.inference import infer_physical_inference

_PROV = Provenance.now(pipeline_version="t", engine="t", engine_version="1.0")


def _q(value, error=None, unit=""):
    return Quantity(value=value, error=error, unit=unit, kind=ValueKind.OBSERVED, method="test")


def _characterization(*, band_flux=None) -> CharacterizationResult:
    return CharacterizationResult.create(
        detection_id="D0", position=SkyPosition(x_px=1.0, y_px=1.0), provenance=_PROV, band_flux=band_flux or {},
    )


def test_no_evidence_at_all_gives_an_empty_chain_with_zero_priority():
    chain = build_evidence_chain(detection_id="D0")
    assert chain.items == ()
    assert chain.priority_index == 0.0
    assert not chain.scientific_candidate_gate


def test_catalog_match_is_recorded_as_neutral_context_not_support():
    # Un catálogo QUE coincide no empuja hacia "candidato de descubrimiento"
    # -- es lo contrario: sugiere que es un objeto ya conocido.
    match = CatalogMatch(catalog="Gaia DR3", catalog_id="123", separation_arcsec=0.5)
    chain = build_evidence_chain(detection_id="D0", catalog_matches=(match,))
    assert len(chain.items) == 1
    assert chain.items[0].category == "catalog_match"
    assert chain.items[0].supports_candidate is False
    assert chain.priority_index == 0.0


def test_real_catalog_non_match_supports_candidacy_but_unreachable_query_does_not():
    real_non_match = CatalogQuery(catalog="Gaia DR3", radius_arcsec=3.0, reason="sin fuentes en el radio de búsqueda")
    unreachable = CatalogQuery(catalog="Gaia DR3", radius_arcsec=3.0, reason="Gaia no disponible: sin conexión de red")

    supports = build_evidence_chain(detection_id="D0", catalog_non_matches=(real_non_match,))
    assert supports.items[0].supports_candidate is True

    does_not_support = build_evidence_chain(detection_id="D0", catalog_non_matches=(unreachable,))
    assert does_not_support.items[0].supports_candidate is False


def test_only_anomaly_dimensions_above_threshold_become_evidence_items():
    chars = _characterization(band_flux={"HA": _q(1000.0, error=50.0, unit="adu")})
    below_threshold = build_anomaly_vector(detection_id="D0", characterization=chars, expected_band_flux={"HA": 950.0})  # z=1
    above_threshold = build_anomaly_vector(detection_id="D0", characterization=chars, expected_band_flux={"HA": 500.0})  # z=10

    chain_below = build_evidence_chain(detection_id="D0", anomaly=below_threshold, anomaly_sigma_threshold=4.0)
    assert chain_below.items == ()

    chain_above = build_evidence_chain(detection_id="D0", anomaly=above_threshold, anomaly_sigma_threshold=4.0)
    assert len(chain_above.items) == 1
    assert chain_above.items[0].category == "photometric_anomaly"
    assert chain_above.items[0].source_engine == "AnomalyEngine.photometric"
    assert chain_above.items[0].supports_candidate is True


def test_physical_tension_becomes_evidence_with_its_assumptions_attached():
    row = {"radius_pc": 5.0, "velocity_kms": 120.0, "age_yr": 1.0, "age_err_yr": 0.01}
    inferred = infer_physical_inference({"radius_pc": 5.0, "velocity_kms": 120.0}, detection_id="D0", object_family="SNR")
    consistency = evaluate_consistency(row, inferred, sigma_threshold=4.0)

    chain = build_evidence_chain(detection_id="D0", consistency=consistency)
    assert len(chain.items) == 1
    item = chain.items[0]
    assert item.category == "physical_tension"
    assert item.source_engine == "PhysicalConstraintEngine"
    assert item.supports_candidate is True
    assert "Sedov" in item.description


def test_temporal_and_motion_only_count_when_the_engine_concluded_something_real():
    inactive_temporal = TemporalEvidence.create(detection_id="D0", n_epochs=1, provenance=_PROV, variable_candidate=False)
    active_temporal = TemporalEvidence.create(
        detection_id="D0", n_epochs=5, provenance=_PROV, variable_candidate=True, brightness_change=_q(2.0, error=0.2, unit="value/epoch"),
    )
    still_motion = MotionEvidence.create(detection_id="D0", n_epochs_used=3, provenance=_PROV, moving_source_candidate=False)
    moving = MotionEvidence.create(
        detection_id="D0", n_epochs_used=3, provenance=_PROV, moving_source_candidate=True, pm_total=_q(24.0, error=3.6, unit="arcsec/hour"),
    )

    quiet = build_evidence_chain(detection_id="D0", temporal=inactive_temporal, motion=still_motion)
    assert quiet.items == ()

    active = build_evidence_chain(detection_id="D0", temporal=active_temporal, motion=moving)
    categories = {item.category for item in active.items}
    assert categories == {"temporal_evidence", "motion_evidence"}
    assert all(item.supports_candidate for item in active.items)


def test_flagged_artifact_checks_count_as_opposing_evidence_never_hidden():
    flagged = ArtifactCheck(kind=ArtifactKind.COSMIC_RAY, flagged=True, confidence=_q(0.9), notes="FWHM 0.4x el campo")
    clean = ArtifactCheck(kind=ArtifactKind.SATURATION, flagged=False, confidence=_q(0.0), notes="sin saturar")

    chain = build_evidence_chain(detection_id="D0", artifact_checks=(flagged, clean))
    assert len(chain.items) == 1  # el check limpio no genera evidencia, ni a favor ni en contra
    assert chain.items[0].category == "artifact_check"
    assert chain.items[0].supports_candidate is False


def test_priority_index_counts_distinct_supporting_engines_minus_artifact_opposition():
    active_temporal = TemporalEvidence.create(
        detection_id="D0", n_epochs=5, provenance=_PROV, variable_candidate=True, brightness_change=_q(2.0, error=0.2, unit="value/epoch"),
    )
    moving = MotionEvidence.create(
        detection_id="D0", n_epochs_used=3, provenance=_PROV, moving_source_candidate=True, pm_total=_q(24.0, error=3.6, unit="arcsec/hour"),
    )
    flagged = ArtifactCheck(kind=ArtifactKind.COSMIC_RAY, flagged=True, confidence=_q(0.9), notes="test")

    chain = build_evidence_chain(detection_id="D0", temporal=active_temporal, motion=moving, artifact_checks=(flagged,))
    # 2 motores independientes a favor (TemporalEngine, MotionEngine) - 1 artefacto en contra = 1.
    assert chain.priority_index == 1.0
    assert set(chain.supporting_engines) == {"TemporalEngine", "MotionEngine"}


def test_priority_index_never_goes_below_zero():
    flagged = ArtifactCheck(kind=ArtifactKind.COSMIC_RAY, flagged=True, confidence=_q(0.9), notes="test")
    chain = build_evidence_chain(detection_id="D0", artifact_checks=(flagged, flagged, flagged))
    assert chain.priority_index == 0.0


def test_scientific_candidate_gate_needs_the_configured_minimum_independent_evidence():
    active_temporal = TemporalEvidence.create(
        detection_id="D0", n_epochs=5, provenance=_PROV, variable_candidate=True, brightness_change=_q(2.0, error=0.2, unit="value/epoch"),
    )
    chain = build_evidence_chain(detection_id="D0", temporal=active_temporal, minimum_independent_evidence=2)
    assert chain.independent_evidence_count == 1
    assert not chain.scientific_candidate_gate  # 1 motor no basta con el mínimo configurado en 2

    lenient_chain = build_evidence_chain(detection_id="D0", temporal=active_temporal, minimum_independent_evidence=1)
    assert lenient_chain.scientific_candidate_gate


def test_roundtrip():
    match = CatalogMatch(catalog="Gaia DR3", catalog_id="123", separation_arcsec=0.5)
    chain = build_evidence_chain(detection_id="D0", catalog_matches=(match,))
    assert EvidenceChain.from_dict(chain.to_dict()) == chain
