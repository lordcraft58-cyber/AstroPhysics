from __future__ import annotations

from datetime import datetime, timezone

import pytest

from astrophysics_suite.core.provenance import Provenance
from astrophysics_suite.reporting.models import DataSeries, ReportField, ReportSection, ScientificResult


def _provenance() -> Provenance:
    return Provenance.now(pipeline_version="v-test", engine="reporting.test", engine_version="1.0")


def test_data_series_rejects_mismatched_x_y_length():
    with pytest.raises(ValueError):
        DataSeries(name="s", x=(0.0, 1.0), y=(1.0,), x_label="t", y_label="v")


def test_data_series_rejects_mismatched_y_error_length():
    with pytest.raises(ValueError):
        DataSeries(name="s", x=(0.0, 1.0), y=(1.0, 2.0), x_label="t", y_label="v", y_error=(0.1,))


def test_data_series_rejects_mismatched_x_categories_length():
    with pytest.raises(ValueError):
        DataSeries(name="s", x=(0.0, 1.0), y=(1.0, 2.0), x_label="t", y_label="v", kind="bar", x_categories=("solo una",))


def test_data_series_accepts_well_formed_series():
    series = DataSeries(name="s", x=(0.0, 1.0, 2.0), y=(1.0, 2.0, 3.0), x_label="t", y_label="v", y_error=(0.1, 0.1, 0.1))
    assert series.kind == "line"
    assert len(series.x) == len(series.y) == len(series.y_error)


def test_data_series_rejects_out_of_range_outlier_indices():
    with pytest.raises(ValueError):
        DataSeries(name="s", x=(0.0, 1.0), y=(1.0, 2.0), x_label="i", y_label="r", kind="residual", outlier_indices=(2,))


def test_data_series_accepts_valid_outlier_indices():
    series = DataSeries(name="s", x=(0.0, 1.0, 2.0), y=(0.1, -0.2, 5.0), x_label="i", y_label="r", kind="residual", outlier_indices=(2,))
    assert series.outlier_indices == (2,)


def test_scientific_result_section_lookup_finds_existing_key():
    result = ScientificResult(
        schema_version=1, subject_id="SUBJ-1", title="t", generated_at=datetime.now(timezone.utc), provenance=_provenance(),
        sections=(ReportSection(key="a", title="A"), ReportSection(key="b", title="B")),
    )
    found = result.section("b")
    assert found is not None
    assert found.title == "B"


def test_scientific_result_section_lookup_returns_none_for_missing_key():
    result = ScientificResult(
        schema_version=1, subject_id="SUBJ-1", title="t", generated_at=datetime.now(timezone.utc), provenance=_provenance(),
    )
    assert result.section("no existe") is None


def test_scientific_result_to_dict_reflects_fields_tables_series_and_notes():
    section = ReportSection(
        key="quality", title="Calidad",
        fields=(ReportField(label="S/N", value="10.0"), ReportField(label="RA", value="NO DISPONIBLE", available=False)),
        series=(DataSeries(name="s", x=(0.0, 1.0), y=(1.0, 2.0), x_label="t", y_label="v"),),
        notes=("nota real",),
    )
    result = ScientificResult(
        schema_version=1, subject_id="SUBJ-1", title="Estudio", generated_at=datetime.now(timezone.utc),
        provenance=_provenance(), sections=(section,),
    )
    data = result.to_dict()
    assert data["subject_id"] == "SUBJ-1"
    assert len(data["sections"]) == 1
    section_dict = data["sections"][0]
    assert section_dict["key"] == "quality"
    assert section_dict["fields"] == [
        {"label": "S/N", "value": "10.0", "available": True},
        {"label": "RA", "value": "NO DISPONIBLE", "available": False},
    ]
    assert section_dict["n_series"] == 1
    assert section_dict["notes"] == ["nota real"]
