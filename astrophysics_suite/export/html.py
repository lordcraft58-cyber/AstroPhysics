"""`ScientificResult` -> HTML autocontenido: un único archivo `.html`
con las gráficas embebidas en base64 (`visualization.charts.render_series`)
y las tablas ya existentes (`tables.table.Table`) como `<table>` real --
sin CSS ni JavaScript externos, para poder abrirlo o compartirlo sin
depender de red ni de archivos auxiliares.
"""
from __future__ import annotations

import base64
import html
from pathlib import Path

from astrophysics_suite.reporting.models import ReportField, ReportSection, ScientificResult
from astrophysics_suite.tables.table import Table
from astrophysics_suite.visualization.charts import render_series

_STYLE = """
body { font-family: -apple-system, Segoe UI, Helvetica, Arial, sans-serif; margin: 0; padding: 0; color: #1a1a1a; background: #fafafa; }
header { background: #1f2a44; color: #fff; padding: 1.5rem 2rem; }
header h1 { margin: 0 0 0.3rem 0; font-size: 1.4rem; }
header p { margin: 0; font-size: 0.85rem; color: #cbd3e6; }
nav { padding: 0.8rem 2rem; background: #eef1f7; border-bottom: 1px solid #d7dce6; font-size: 0.85rem; }
nav a { margin-right: 1rem; color: #1f2a44; text-decoration: none; }
nav a:hover { text-decoration: underline; }
main { max-width: 980px; margin: 0 auto; padding: 1.5rem 2rem 3rem 2rem; }
section { background: #fff; border: 1px solid #e0e4ec; border-radius: 6px; padding: 1.2rem 1.5rem; margin-bottom: 1.2rem; }
section h2 { margin-top: 0; font-size: 1.1rem; border-bottom: 1px solid #eee; padding-bottom: 0.4rem; }
dl.fields { display: grid; grid-template-columns: max-content 1fr; gap: 0.25rem 1rem; margin: 0.8rem 0; }
dl.fields dt { font-weight: 600; color: #444; }
dl.fields dd { margin: 0; }
dd.unavailable { color: #a33; font-style: italic; }
table.data { border-collapse: collapse; width: 100%; margin: 0.8rem 0; font-size: 0.85rem; }
table.data th, table.data td { border: 1px solid #ddd; padding: 0.3rem 0.5rem; text-align: left; }
table.data th { background: #f0f2f7; }
table.data tr:nth-child(even) { background: #fafbfc; }
.chart { margin: 0.8rem 0; }
.chart img { max-width: 100%; border: 1px solid #e0e4ec; border-radius: 4px; }
ul.notes { margin: 0.6rem 0 0 0; padding-left: 1.2rem; font-size: 0.85rem; color: #555; }
footer { max-width: 980px; margin: 0 auto; padding: 0 2rem 2rem 2rem; font-size: 0.78rem; color: #888; }
"""


def render_html(result: ScientificResult) -> str:
    """Construye el HTML completo en memoria -- el llamador decide si lo
    guarda (`export_html`), lo sirve o lo inspecciona en una prueba,
    igual que `render_series` nunca escribe a disco por sí sola."""
    parts: list[str] = []
    parts.append("<!doctype html>")
    parts.append('<html lang="es"><head><meta charset="utf-8">')
    parts.append(f"<title>{html.escape(result.title)}</title>")
    parts.append(f"<style>{_STYLE}</style></head><body>")
    parts.append("<header>")
    parts.append(f"<h1>{html.escape(result.title)}</h1>")
    parts.append(
        f"<p>Sujeto: {html.escape(result.subject_id)} &middot; "
        f"Generado: {result.generated_at:%Y-%m-%d %H:%M UTC} &middot; "
        f"{html.escape(result.provenance.engine)} {html.escape(result.provenance.engine_version)}</p>"
    )
    parts.append("</header>")

    parts.append("<nav>")
    for section in result.sections:
        parts.append(f'<a href="#{html.escape(section.key)}">{html.escape(section.title)}</a>')
    parts.append("</nav>")

    parts.append("<main>")
    for section in result.sections:
        parts.append(_render_section(section))
    parts.append("</main>")

    parts.append(
        f"<footer>Informe generado por {html.escape(result.provenance.engine)} "
        f"{html.escape(result.provenance.engine_version)} "
        f"({result.provenance.produced_at:%Y-%m-%d %H:%M UTC})"
        + (f" &mdash; pipeline {html.escape(result.provenance.pipeline_version)}" if result.provenance.pipeline_version else "")
        + "</footer>"
    )
    parts.append("</body></html>")
    return "\n".join(parts)


def _render_section(section: ReportSection) -> str:
    parts = [f'<section id="{html.escape(section.key)}">', f"<h2>{html.escape(section.title)}</h2>"]
    if section.fields:
        parts.append(_render_fields(section.fields))
    for table in section.tables:
        parts.append(_render_table(table))
    for series in section.series:
        parts.append(_render_chart(series))
    if section.notes:
        parts.append("<ul class='notes'>")
        parts.extend(f"<li>{html.escape(note)}</li>" for note in section.notes)
        parts.append("</ul>")
    parts.append("</section>")
    return "\n".join(parts)


def _render_fields(fields: tuple[ReportField, ...]) -> str:
    rows = []
    for f in fields:
        cls = "" if f.available else " class='unavailable'"
        rows.append(f"<dt>{html.escape(f.label)}</dt><dd{cls}>{html.escape(f.value)}</dd>")
    return "<dl class='fields'>" + "".join(rows) + "</dl>"


def _render_table(table: Table) -> str:
    if not table.rows:
        return ""
    header = "".join(f"<th>{html.escape(_column_label(name, unit))}</th>" for name, unit in zip(table.columns, table.units))
    body = "".join(
        "<tr>" + "".join(f"<td>{html.escape(_format_cell(v))}</td>" for v in row) + "</tr>" for row in table.rows
    )
    return f"<table class='data'><thead><tr>{header}</tr></thead><tbody>{body}</tbody></table>"


def _column_label(name: str, unit: str) -> str:
    return f"{name} [{unit}]" if unit else name


def _format_cell(value: object) -> str:
    if isinstance(value, float):
        return f"{value:.6g}"
    return str(value)


def _render_chart(series) -> str:
    png = render_series(series, title=series.name)
    encoded = base64.b64encode(png).decode("ascii")
    return f"<div class='chart'><img src='data:image/png;base64,{encoded}' alt=\"{html.escape(series.name)}\"></div>"


def export_html(result: ScientificResult, path: str) -> None:
    """Genera el informe HTML y lo escribe en `path` -- único archivo,
    autocontenido, listo para compartir o archivar."""
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(render_html(result), encoding="utf-8")
