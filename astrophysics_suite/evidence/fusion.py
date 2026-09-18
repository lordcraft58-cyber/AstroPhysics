"""Fusión de evidencia por fila -> `EvidenceChain`.
"""
from __future__ import annotations

from legacy.AstroPhysicsSuite_v57_3_COMMERCIAL import DiscoveryEvidenceEngine as _LegacyDiscoveryEvidenceEngine

from astrophysics_suite.core.enums import ValueKind
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.evidence import DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE, EvidenceChain, EvidenceItem

ENGINE_NAME = "evidence.fusion"


def evidence_chain_from_row(
    row: dict,
    *,
    detection_id: str,
    object_family: str = "unknown",
    reference: dict | None = None,
    ai_result: dict | None = None,
    sigma_threshold: float = 4.0,
    minimum_independent_evidence: int = DEFAULT_MINIMUM_INDEPENDENT_EVIDENCE,
) -> EvidenceChain:
    engine = _LegacyDiscoveryEvidenceEngine(sigma_threshold=sigma_threshold)
    result = engine.evaluate_rows(
        [row], object_family=object_family, reference=reference, ai_results=[ai_result] if ai_result is not None else None
    )
    rec = result["rows"][0]

    items: list[EvidenceItem] = []

    phys_issues = [c for c in rec["constraints"]["issues"] if c.get("flag") and c.get("classification") != "measurement_issue"]
    if phys_issues:
        z_values = [abs(c["z_score"]) for c in phys_issues if c.get("z_score") is not None]
        items.append(
            EvidenceItem(
                category="physical_tension",
                description="; ".join(c["constraint"] for c in phys_issues),
                source_engine="PhysicalConstraintEngine",
                supports_candidate=True,
                value=Quantity(value=max(z_values), error=None, unit="sigma", kind=ValueKind.OBSERVED, method="PhysicalConstraintEngine")
                if z_values
                else None,
            )
        )

    ref_sig = [x for x in rec["reference_anomalies"] if x.get("z_score") is not None and abs(x["z_score"]) >= sigma_threshold]
    if ref_sig:
        items.append(
            EvidenceItem(
                category="reference_anomaly",
                description="; ".join(f"{x['parameter']} ({x['direction']})" for x in ref_sig),
                source_engine="ReferenceComparisonEngine",
                supports_candidate=True,
                value=Quantity(value=max(abs(x["z_score"]) for x in ref_sig), error=None, unit="sigma", kind=ValueKind.OBSERVED, method="build_reference_anomaly"),
            )
        )

    if rec["evidence_components"]["model_discrepancy"] > 0:
        items.append(
            EvidenceItem(
                category="model_discrepancy",
                description="Discrepancia significativa entre modelos físicos comparados",
                source_engine="ModelComparisonEngine",
                supports_candidate=True,
            )
        )

    if rec["evidence_components"]["visual_novelty"] > 0:
        items.append(
            EvidenceItem(
                category="visual_novelty",
                description="Señal de novedad visual reportada por IA",
                source_engine="DiscoveryAI",
                supports_candidate=True,
            )
        )

    return EvidenceChain.create(
        detection_id=detection_id,
        items=tuple(items),
        priority_index=rec["priority_index"],
        minimum_independent_evidence=minimum_independent_evidence,
    )
