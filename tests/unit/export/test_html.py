"""`render_html`/`export_html` contra un `ScientificResult` real (con
campos, tablas y series REALES) -- confirma que el HTML producido es
autocontenido (gráficas embebidas en base64, sin CSS/JS externo), que
respeta el orden de secciones, y que `export_html` escribe el archivo
de verdad en disco."""
from __future__ import annotations

from datetime import datetime, timezone

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.export.html import export_html, render_html
from astrophysics_suite.reporting.models import DataSeries, ReportField, ReportSection, ScientificResult
from astrophysics_suite.tables.table import Table


def _provenance() -> Provenance:
    return Provenance.now(pipeline_version="v-html-test", engine="reporting.test", engine_version="1.0")


def _result_with_everything() -> ScientificResult:
    observation_section = ReportSection(
        key="observation", title="1. Observación",
        fields=(ReportField(label="Objetivo", value="Campo de prueba"),),
    )
    quality_section = ReportSection(
        key="quality", title="2. Calidad",
        fields=(
            ReportField(label="S/N", value="599.1"),
            ReportField(label="RA/Dec", value="NO DISPONIBLE (sin WCS)", available=False),
        ),
        tables=(Table(columns=("check", "nivel"), units=("", ""), rows=(("morphology_screen", "PASS"),)),),
    )
    temporal_section = ReportSection(
        key="temporal", title="6. Temporal",
        series=(
            DataSeries(
                name="Curva de luz", x=(0.0, 1.0, 2.0), y=(1000.0, 1010.0, 1025.0),
                x_label="t", y_label="brillo", x_unit="h", y_unit="ADU", kind="line",
            ),
        ),
        notes=("candidato variable detectado",),
    )
    return ScientificResult(
        schema_version=1, subject_id="APS-000124", title="Estudio científico -- APS-000124",
        generated_at=datetime(2026, 1, 1, 12, 0, tzinfo=timezone.utc), provenance=_provenance(),
        sections=(observation_section, quality_section, temporal_section),
    )


def test_render_html_embeds_exactly_one_chart_per_series():
    result = _result_with_everything()
    html_text = render_html(result)
    assert html_text.count("data:image/png;base64,") == 1


def test_render_html_contains_no_external_stylesheet_or_script_references():
    result = _result_with_everything()
    html_text = render_html(result)
    assert "http://" not in html_text
    assert "https://" not in html_text
    assert "<link" not in html_text
    assert "<script" not in html_text


def test_render_html_shows_real_field_values_and_marks_unavailable_ones():
    result = _result_with_everything()
    html_text = render_html(result)
    assert "599.1" in html_text
    assert "NO DISPONIBLE (sin WCS)" in html_text
    assert "class='unavailable'" in html_text


def test_render_html_renders_table_rows():
    result = _result_with_everything()
    html_text = render_html(result)
    assert "morphology_screen" in html_text
    assert "PASS" in html_text


def test_render_html_includes_notes_and_subject_id():
    result = _result_with_everything()
    html_text = render_html(result)
    assert "candidato variable detectado" in html_text
    assert "APS-000124" in html_text


def test_render_html_preserves_section_order_via_navigation_links():
    result = _result_with_everything()
    html_text = render_html(result)
    positions = [html_text.index(f'href="#{key}"') for key in ("observation", "quality", "temporal")]
    assert positions == sorted(positions)


def test_export_html_writes_a_real_file_to_disk(tmp_path):
    result = _result_with_everything()
    out_path = tmp_path / "reports" / "informe.html"

    export_html(result, str(out_path))

    assert out_path.exists()
    text = out_path.read_text(encoding="utf-8")
    assert text.startswith("<!doctype html>")
    assert text == render_html(result)
