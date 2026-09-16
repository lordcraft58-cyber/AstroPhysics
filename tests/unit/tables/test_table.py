from __future__ import annotations

import pytest

from astrophysics_suite.tables.table import Table


def test_table_rejects_mismatched_units_length():
    with pytest.raises(ValueError):
        Table(columns=("x", "y"), units=("px",), rows=())


def test_table_rejects_row_with_wrong_arity():
    with pytest.raises(ValueError):
        Table(columns=("x", "y"), units=("px", "px"), rows=((1.0,),))


def test_table_to_csv_and_from_csv_roundtrips_real_file(tmp_path):
    table = Table(
        columns=("star_id", "x", "y", "flux"),
        units=("", "px", "px", "ADU"),
        rows=((1, 10.5, 20.25, 30000.0), (2, 15.0, 22.0, 12000.5)),
    )
    path = tmp_path / "measurements.csv"

    table.to_csv(str(path))
    assert path.exists()

    loaded = Table.from_csv(str(path))

    assert loaded.columns == table.columns
    assert loaded.units == table.units
    assert loaded.rows == table.rows


def test_table_to_csv_writes_readable_header_with_units(tmp_path):
    table = Table(columns=("ra", "dec"), units=("deg", "deg"), rows=((150.0, 2.0),))
    path = tmp_path / "coords.csv"

    table.to_csv(str(path))

    content = path.read_text(encoding="utf-8")
    assert "ra [deg]" in content
    assert "dec [deg]" in content


def test_table_to_csv_omits_brackets_for_columns_without_units(tmp_path):
    table = Table(columns=("name",), units=("",), rows=(("star_a",),))
    path = tmp_path / "names.csv"

    table.to_csv(str(path))

    content = path.read_text(encoding="utf-8")
    assert content.splitlines()[0].strip() == "name"


def test_table_from_csv_infers_int_and_float_and_string_types(tmp_path):
    path = tmp_path / "mixed.csv"
    path.write_text("id [],value [mag],label []\n1,2.5,star\n2,3.0,other\n", encoding="utf-8")

    table = Table.from_csv(str(path))

    assert table.columns == ("id", "value", "label")
    assert table.units == ("", "mag", "")
    assert table.rows[0] == (1, 2.5, "star")
    assert isinstance(table.rows[0][0], int)
    assert isinstance(table.rows[0][1], float)


def test_table_to_csv_creates_missing_parent_directories(tmp_path):
    table = Table(columns=("x",), units=("",), rows=((1.0,),))
    path = tmp_path / "nested" / "output" / "table.csv"

    table.to_csv(str(path))

    assert path.exists()


def test_table_from_csv_empty_file_returns_empty_table(tmp_path):
    path = tmp_path / "empty.csv"
    path.write_text("", encoding="utf-8")

    table = Table.from_csv(str(path))

    assert table.columns == ()
    assert table.rows == ()
