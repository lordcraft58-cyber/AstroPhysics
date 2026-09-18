"""`Observation` + su lista real de `Candidate` -> `ScientificResult`
agregado -- el resumen de UNA corrida de Discovery completa, no de un
candidato aislado (ver `reporting.candidate_report` para eso). Cada
número aquí es un conteo/agregado real sobre los candidatos recibidos:
nunca una estimación ni una media sobre datos que no llegaron.
"""
from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation
from astrophysics_suite.reporting.candidate_report import ANOMALY_DIMENSIONS, ANOMALY_LABELS
from astrophysics_suite.reporting.models import DataSeries, ReportField, ReportSection, ScientificResult
from astrophysics_suite.tables.table import Table

ENGINE_NAME = "reporting.observation_report"
ENGINE_VERSION = "1.0"


def _count_by(candidates: tuple[Candidate, ...], key) -> dict[str, int]:
    counts: dict[str, int] = {}
    for c in candidates:
        label = key(c)
        counts[label] = counts.get(label, 0) + 1
    return counts


def _section_summary(observation: Observation | None, candidates: tuple[Candidate, ...]) -> ReportSection:
    fields = [ReportField(label="Candidatos totales", value=str(len(candidates)))]
    if observation is not None:
        fields.insert(0, ReportField(label="Objetivo", value=observation.target_name or "—"))
        fields.insert(1, ReportField(label="Imágenes", value=str(len(observation.images))))
    else:
        fields.append(ReportField(label="Observación", value="NO DISPONIBLE (no se adjuntó al generar el informe)", available=False))

    state_counts = _count_by(candidates, lambda c: c.identification_state.value)
    table = Table(
        columns=("estado de identificación", "candidatos"), units=("", ""),
        rows=tuple(sorted(state_counts.items(), key=lambda kv: -kv[1])),
    )
    review_counts = _count_by(candidates, lambda c: c.review_state.value)
    review_table = Table(
        columns=("estado de revisión", "candidatos"), units=("", ""),
        rows=tuple(sorted(review_counts.items(), key=lambda kv: -kv[1])),
    )
    return ReportSection(key="summary", title="1. Resumen", fields=tuple(fields), tables=(table, review_table))


def _section_quality(candidates: tuple[Candidate, ...]) -> ReportSection:
    if not candidates:
        return ReportSection(key="quality", title="2. Calidad", fields=(ReportField(label="Calidad", value="NO DISPONIBLE (sin candidatos)", available=False),))
    level_counts = _count_by(candidates, lambda c: c.quality.overall_level.value)
    n_flagged_artifacts = sum(1 for c in candidates if any(a.flagged for a in c.artifact_checks))
    fields = [ReportField(label="Candidatos con algún artefacto marcado", value=str(n_flagged_artifacts))]
    table = Table(
        columns=("nivel general", "candidatos"), units=("", ""),
        rows=tuple(sorted(level_counts.items(), key=lambda kv: -kv[1])),
    )
    return ReportSection(key="quality", title="2. Calidad", fields=tuple(fields), tables=(table,))


def _section_anomaly(candidates: tuple[Candidate, ...]) -> ReportSection:
    per_dimension: dict[str, list[float]] = {name: [] for name in ANOMALY_DIMENSIONS}
    for c in candidates:
        if c.anomaly_evidence is None:
            continue
        for name in ANOMALY_DIMENSIONS:
            q = getattr(c.anomaly_evidence, name)
            if q is not None and q.is_available:
                per_dimension[name].append(q.value)

    available = [(name, values) for name, values in per_dimension.items() if values]
    fields = [
        ReportField(label=ANOMALY_LABELS[name], value=f"{len(values)} candidato(s), máx {max(values):.4g} sigma")
        for name, values in available
    ]
    if not available:
        fields.append(ReportField(label="Vector de anomalía", value="NO DISPONIBLE (ningún candidato con dimensiones evaluadas)", available=False))

    series: tuple[DataSeries, ...] = ()
    if available:
        series = (DataSeries(
            name="Anomalía máxima por dimensión", x=tuple(range(len(available))), y=tuple(max(values) for _n, values in available),
            x_label="Dimensión", y_label="Significancia máxima", y_unit="sigma", kind="bar",
            x_categories=tuple(ANOMALY_LABELS[n] for n, _v in available),
        ),)
    return ReportSection(key="anomaly", title="3. Anomalías", fields=tuple(fields), series=series)


def _section_evidence(candidates: tuple[Candidate, ...]) -> ReportSection:
    with_chain = [c for c in candidates if c.evidence_chain is not None]
    n_gate = sum(1 for c in with_chain if c.evidence_chain.scientific_candidate_gate)
    fields = [
        ReportField(label="Candidatos con cadena de evidencia", value=str(len(with_chain))),
        ReportField(label="Superan el gate científico (>= evidencia mínima)", value=str(n_gate)),
    ]
    top = sorted(with_chain, key=lambda c: c.evidence_chain.priority_index, reverse=True)[:10]
    table = Table(
        columns=("candidato", "estado", "índice de prioridad", "motores independientes"), units=("", "", "", ""),
        rows=tuple((c.candidate_id, c.identification_state.value, c.evidence_chain.priority_index, c.evidence_chain.independent_evidence_count) for c in top),
    )
    return ReportSection(key="evidence", title="4. Evidencia", fields=tuple(fields), tables=(table,) if top else ())


def _section_provenance(provenance: Provenance) -> ReportSection:
    fields = [
        ReportField(label="Pipeline", value=provenance.pipeline_version or "—"),
        ReportField(label="Motor", value=f"{provenance.engine} {provenance.engine_version}"),
        ReportField(label="Producido", value=f"{provenance.produced_at:%Y-%m-%d %H:%M UTC}"),
    ]
    return ReportSection(key="provenance", title="5. Procedencia", fields=tuple(fields))


def build_observation_report(
    observation: Observation | None, candidates: list[Candidate] | tuple[Candidate, ...], *, pipeline_version: str = "",
) -> ScientificResult:
    """Agrega TODOS los `candidates` recibidos -- no vuelve a ejecutar
    ningún motor ni recalcula nada, solo cuenta y resume lo que cada
    `Candidate` ya trae. Pensado para una corrida completa de Discovery
    sobre una `Observation`, pero funciona igual con cualquier lista real
    de candidatos (p. ej. una selección filtrada por el usuario)."""
    candidates = tuple(candidates)
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    subject_id = observation.observation_id if observation is not None else "(sin observación adjunta)"
    title = f"Resumen de observación -- {observation.target_name}" if observation is not None else "Resumen de observación"
    sections = (
        _section_summary(observation, candidates),
        _section_quality(candidates),
        _section_anomaly(candidates),
        _section_evidence(candidates),
        _section_provenance(provenance),
    )
    return ScientificResult(
        schema_version=1, subject_id=subject_id, title=title,
        generated_at=datetime.now(timezone.utc), provenance=provenance, sections=sections,
    )
