"""`Candidate` (con toda su cadena de evidencia real) -> `ScientificResult`
de 13 secciones -- el "estudio científico completo" de un candidato.

Cada sección se construye ÚNICAMENTE a partir de datos que algún motor
ya midió de verdad: cuando un motor no corrió sobre esta fuente (p. ej.
sin física inferida en modo genérico, sin WCS por imagen porque este
informe solo recibe el `Candidate`), la sección lo dice explícitamente
en vez de dejar un hueco silencioso o inventar un valor.
"""
from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.core.quantity import Quantity
from astrophysics_suite.models.candidate import Candidate
from astrophysics_suite.models.observation import Observation
from astrophysics_suite.reporting.models import DataSeries, ReportField, ReportSection, ScientificResult
from astrophysics_suite.tables.table import Table

ENGINE_NAME = "reporting.candidate_report"
ENGINE_VERSION = "1.0"

ANOMALY_DIMENSIONS = ("photometric", "morphological", "spectral", "temporal", "astrometric", "spatial", "physical")
ANOMALY_LABELS = {
    "photometric": "Fotométrica", "morphological": "Morfológica", "spectral": "Espectral",
    "temporal": "Temporal", "astrometric": "Astrométrica", "spatial": "Espacial", "physical": "Física",
}


def _fmt_quantity(q: Quantity | None) -> str:
    if q is None or not q.is_available:
        return "NO DISPONIBLE"
    text = f"{q.value:.4g}"
    if q.error is not None:
        text += f" ± {q.error:.2g}"
    if q.unit:
        text += f" {q.unit}"
    return text


def _field(label: str, q: Quantity | None) -> ReportField:
    return ReportField(label=label, value=_fmt_quantity(q), available=q is not None and q.is_available)


def _section_observation(candidate: Candidate, observation: Observation | None) -> ReportSection:
    if observation is None:
        return ReportSection(
            key="observation", title="1. Observación",
            fields=(ReportField(label="Observación", value="NO DISPONIBLE (no se adjuntó al generar el informe)", available=False),),
        )
    fields = [
        ReportField(label="Objetivo", value=observation.target_name or "—"),
        ReportField(label="Instrumento", value=observation.instrument or "—"),
        ReportField(label="Creada", value=f"{observation.created_at:%Y-%m-%d %H:%M UTC}"),
    ]
    if observation.epoch:
        fields.append(ReportField(label="Época", value=f"{observation.epoch:%Y-%m-%d %H:%M UTC}"))
    table = Table(
        columns=("archivo", "banda", "rol", "escala", "WCS"),
        units=("", "", "", "arcsec/px", ""),
        rows=tuple(
            (im.path, im.band, im.role, im.pixel_scale_arcsec if im.pixel_scale_arcsec is not None else "—", "sí" if im.has_wcs else "no")
            for im in observation.images
        ),
    )
    return ReportSection(key="observation", title="1. Observación", fields=tuple(fields), tables=(table,))


def _section_quality(candidate: Candidate) -> ReportSection:
    fields = [
        _field("S/N", candidate.snr),
        _field("FWHM", candidate.size),
        ReportField(label="Nivel general", value=candidate.quality.overall_level.value),
    ]
    table = Table(
        columns=("comprobación", "nivel", "detalle"), units=("", "", ""),
        rows=tuple((c.name, c.level.value, c.detail) for c in candidate.quality.checks),
    )
    artifacts_table = Table(
        columns=("artefacto", "marcado", "confianza", "notas"), units=("", "", "", ""),
        rows=tuple((a.kind.value, "sí" if a.flagged else "no", _fmt_quantity(a.confidence), a.notes) for a in candidate.artifact_checks),
    )
    return ReportSection(key="quality", title="2. Calidad", fields=tuple(fields), tables=(table, artifacts_table))


def _section_astrometry(candidate: Candidate) -> ReportSection:
    pos = candidate.position
    fields = [
        ReportField(label="X (px)", value=f"{pos.x_px:.2f}"),
        ReportField(label="Y (px)", value=f"{pos.y_px:.2f}"),
    ]
    if pos.has_sky_coordinates:
        fields.append(ReportField(label="RA", value=f"{pos.ra_deg:.6f}°"))
        fields.append(ReportField(label="Dec", value=f"{pos.dec_deg:.6f}°"))
    else:
        fields.append(ReportField(label="RA/Dec", value="NO DISPONIBLE (sin WCS en la imagen de referencia)", available=False))
    fields.append(ReportField(
        label="WCS / RMS del ajuste de placa",
        value="NO DISPONIBLE (resultado por imagen, no por candidato -- este informe no recibió el PlateSolveResult)",
        available=False,
    ))
    return ReportSection(key="astrometry", title="3. Astrometría", fields=tuple(fields))


def _section_photometry(candidate: Candidate) -> ReportSection:
    fields: list[ReportField] = []
    if not candidate.flux:
        fields.append(ReportField(label="Flujo", value="NO DISPONIBLE (sin FWHM medida no se pudo dimensionar una apertura)", available=False))
    for band, flux in candidate.flux.items():
        fields.append(_field(f"Flujo ({band})", flux))
    fields.append(ReportField(
        label="Magnitud calibrada", value="NO DISPONIBLE (necesita un punto cero fotométrico de campo, no forma parte de este candidato)",
        available=False,
    ))
    table = Table(
        columns=("banda", "flujo", "incertidumbre", "unidad", "método"), units=("", "", "", "", ""),
        rows=tuple((band, q.value, q.error, q.unit, q.method) for band, q in candidate.flux.items()),
    )
    return ReportSection(key="photometry", title="4. Fotometría", fields=tuple(fields), tables=(table,))


def _section_morphology(candidate: Candidate) -> ReportSection:
    morph = candidate.morphology
    fields = [
        _field("FWHM", candidate.size),
        ReportField(label="Elongación", value=f"{morph.elongation:.3f}"),
        ReportField(label="Área (px)", value=f"{morph.area_px:.2f}"),
        ReportField(label="Compacidad", value=f"{morph.compactness:.3f}"),
        ReportField(label="Clasificación", value=morph.morphology_class.value),
    ]
    return ReportSection(key="morphology", title="5. Morfología", fields=tuple(fields))


def _section_temporal(candidate: Candidate) -> ReportSection:
    ev = candidate.temporal_evidence
    if ev is None:
        return ReportSection(
            key="temporal", title="6. Temporal",
            fields=(ReportField(label="Variabilidad", value="NO DISPONIBLE (menos de 2 épocas con brillo medido)", available=False),),
        )
    fields = [
        ReportField(label="Épocas", value=str(ev.n_epochs)),
        ReportField(label="Candidato variable", value="Sí" if ev.variable_candidate else "No"),
        _field("Cambio de brillo", ev.brightness_change),
    ]
    if ev.notes:
        fields.append(ReportField(label="Notas", value="; ".join(ev.notes)))
    series: tuple[DataSeries, ...] = ()
    if len(ev.epochs) >= 2:
        series = (DataSeries(
            name="Curva de luz", x=tuple(e.time for e in ev.epochs), y=tuple(e.value for e in ev.epochs),
            x_label="Tiempo relativo", y_label="Brillo instrumental", x_unit="h", y_unit="ADU (pico)",
            y_error=tuple(e.error if e.error is not None else 0.0 for e in ev.epochs), kind="line",
        ),)
    table = Table(
        columns=("t", "valor", "error"), units=("h", "ADU", "ADU"),
        rows=tuple((e.time, e.value, e.error) for e in ev.epochs),
    )
    return ReportSection(key="temporal", title="6. Temporal", fields=tuple(fields), tables=(table,) if ev.epochs else (), series=series)


def _section_motion(candidate: Candidate) -> ReportSection:
    ev = candidate.motion_evidence
    if ev is None:
        return ReportSection(
            key="motion", title="7. Movimiento",
            fields=(ReportField(label="Movimiento propio", value="NO DISPONIBLE (menos de 2 épocas con coordenadas celestes)", available=False),),
        )
    fields = [
        ReportField(label="Épocas usadas", value=str(ev.n_epochs_used)),
        ReportField(label="Candidato en movimiento", value="Sí" if ev.moving_source_candidate else "No"),
        _field("Movimiento propio total", ev.pm_total),
        _field("Movimiento propio (RA)", ev.pm_ra),
        _field("Movimiento propio (Dec)", ev.pm_dec),
    ]
    series: tuple[DataSeries, ...] = ()
    if len(ev.epochs) >= 2:
        series = (DataSeries(
            name="Trayectoria", x=tuple(e.ra_deg for e in ev.epochs), y=tuple(e.dec_deg for e in ev.epochs),
            x_label="RA", y_label="Dec", x_unit="deg", y_unit="deg", kind="scatter",
        ),)
    table = Table(
        columns=("tiempo", "RA", "Dec"), units=("", "deg", "deg"),
        rows=tuple((e.time.isoformat(), e.ra_deg, e.dec_deg) for e in ev.epochs),
    )
    return ReportSection(key="motion", title="7. Movimiento", fields=tuple(fields), tables=(table,) if ev.epochs else (), series=series)


def _section_physical(candidate: Candidate) -> ReportSection:
    inf = candidate.physical_evidence
    if inf is None:
        return ReportSection(
            key="physical", title="8. Física",
            fields=(ReportField(label="Inferencia física", value="NO DISPONIBLE (no se ejecutó para este candidato -- modo genérico sin observables físicos)", available=False),),
        )
    fields = [
        ReportField(label="Familia de objeto", value=inf.object_family or "—"),
        ReportField(label="Modelo", value=inf.model_id or "(sin modelo aplicado)"),
        ReportField(label="Hipótesis", value=", ".join(inf.model_hypotheses) or "—"),
        ReportField(label="Dominio válido", value="Sí" if inf.domain_valid else "No"),
    ]
    table = Table(
        columns=("parámetro", "valor", "incertidumbre", "unidad"), units=("", "", "", ""),
        rows=tuple((name, q.value, q.error, q.unit) for name, q in inf.parameters.items()),
    )
    return ReportSection(key="physical", title="8. Física", fields=tuple(fields), tables=(table,) if inf.parameters else ())


def _section_anomaly(candidate: Candidate) -> ReportSection:
    vec = candidate.anomaly_evidence
    if vec is None:
        return ReportSection(
            key="anomaly", title="9. Anomalías",
            fields=(ReportField(label="Vector de anomalía", value="NO DISPONIBLE", available=False),),
        )
    fields = [_field(ANOMALY_LABELS[name], getattr(vec, name)) for name in ANOMALY_DIMENSIONS]
    fields.append(ReportField(label="Dimensiones disponibles", value=str(vec.independent_evidence_count)))
    available = [(name, getattr(vec, name)) for name in ANOMALY_DIMENSIONS if (q := getattr(vec, name)) is not None and q.is_available]
    series: tuple[DataSeries, ...] = ()
    if available:
        series = (DataSeries(
            name="Vector de anomalía", x=tuple(range(len(available))), y=tuple(q.value for _n, q in available),
            x_label="Dimensión", y_label="Significancia", y_unit="sigma", kind="bar",
            x_categories=tuple(ANOMALY_LABELS[n] for n, _q in available),
        ),)
    return ReportSection(key="anomaly", title="9. Anomalías", fields=tuple(fields), series=series)


def _section_evidence(candidate: Candidate) -> ReportSection:
    chain = candidate.evidence_chain
    if chain is None:
        return ReportSection(
            key="evidence", title="10. Evidencia",
            fields=(ReportField(label="Cadena de evidencia", value="NO DISPONIBLE", available=False),),
        )
    fields = [
        ReportField(label="Índice de prioridad", value=f"{chain.priority_index:.3f}"),
        ReportField(label="Motores independientes a favor", value=str(chain.independent_evidence_count)),
        ReportField(label="Motores", value=", ".join(chain.supporting_engines) or "—"),
        ReportField(label="Mínimo exigido", value=str(chain.minimum_independent_evidence)),
        ReportField(label="Supera el mínimo (gate científico)", value="Sí" if chain.scientific_candidate_gate else "No"),
    ]
    table = Table(
        columns=("categoría", "motor", "a favor", "descripción", "valor"), units=("", "", "", "", ""),
        rows=tuple((it.category, it.source_engine, "sí" if it.supports_candidate else "no", it.description, _fmt_quantity(it.value)) for it in chain.items),
    )
    return ReportSection(key="evidence", title="10. Evidencia", fields=tuple(fields), tables=(table,) if chain.items else ())


def _section_catalogs(candidate: Candidate) -> ReportSection:
    fields = [ReportField(label="Estado de identificación", value=candidate.identification_state.value)]
    matches_table = Table(
        columns=("catálogo", "ID", "separación", "tipo", "magnitud"), units=("", "", "arcsec", "", ""),
        rows=tuple((m.catalog, m.catalog_id, m.separation_arcsec, m.object_type, _fmt_quantity(m.magnitude)) for m in candidate.catalog_matches),
    )
    non_matches_table = Table(
        columns=("catálogo", "radio", "motivo"), units=("", "arcsec", ""),
        rows=tuple((q.catalog, q.radius_arcsec, q.reason) for q in candidate.catalog_non_matches),
    )
    return ReportSection(key="catalogs", title="11. Catálogos", fields=tuple(fields), tables=(matches_table, non_matches_table))


def _section_provenance(candidate: Candidate) -> ReportSection:
    prov = candidate.provenance
    fields = [
        ReportField(label="Pipeline", value=prov.pipeline_version or "—"),
        ReportField(label="Motor", value=f"{prov.engine} {prov.engine_version}"),
        ReportField(label="Producido", value=f"{prov.produced_at:%Y-%m-%d %H:%M UTC}"),
    ]
    if prov.warnings:
        fields.append(ReportField(label="Advertencias", value="; ".join(prov.warnings)))
    return ReportSection(key="provenance", title="12. Procedencia", fields=tuple(fields))


def _section_review(candidate: Candidate) -> ReportSection:
    fields = [ReportField(label="Estado de revisión", value=candidate.review_state.value)]
    table = Table(
        columns=("autor", "fecha", "de", "a", "nota"), units=("", "", "", "", ""),
        rows=tuple((n.author, n.created_at.isoformat(), n.previous_state.value if n.previous_state else "—", n.new_state.value, n.note) for n in candidate.review_notes),
    )
    return ReportSection(key="review", title="13. Revisión humana", fields=tuple(fields), tables=(table,) if candidate.review_notes else ())


def build_candidate_report(
    candidate: Candidate, *, observation: Observation | None = None, pipeline_version: str = "",
) -> ScientificResult:
    """Ensambla las 13 secciones del estudio científico completo de un
    candidato. `observation` es opcional -- sin ella, la sección 1 queda
    honestamente NOT_AVAILABLE en vez de bloquear todo el informe (un
    `Candidate` cargado de una sesión guardada puede no traer su
    `Observation` asociada, ver `io.session_export`)."""
    provenance = Provenance.now(pipeline_version=pipeline_version, engine=ENGINE_NAME, engine_version=ENGINE_VERSION)
    sections = (
        _section_observation(candidate, observation),
        _section_quality(candidate),
        _section_astrometry(candidate),
        _section_photometry(candidate),
        _section_morphology(candidate),
        _section_temporal(candidate),
        _section_motion(candidate),
        _section_physical(candidate),
        _section_anomaly(candidate),
        _section_evidence(candidate),
        _section_catalogs(candidate),
        _section_provenance(candidate),
        _section_review(candidate),
    )
    return ScientificResult(
        schema_version=1, subject_id=candidate.candidate_id, title=f"Estudio científico -- {candidate.candidate_id}",
        generated_at=datetime.now(timezone.utc), provenance=provenance, sections=sections,
    )
