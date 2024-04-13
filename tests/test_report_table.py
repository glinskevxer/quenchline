from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.report.table import Align, Column, Table, render_kv


def build() -> Table:
    table = Table(
        columns=[
            Column("furnace"),
            Column("class", align=Align.CENTRE),
            Column("spread", align=Align.RIGHT, places=1),
        ]
    )
    table.add("HT-04", "2", 14.2)
    table.add("HT-11", "3", 7.0)
    return table


def test_headers_and_rule_line() -> None:
    lines = build().render().splitlines()
    assert lines[0] == "furnace  class  spread"
    assert lines[1] == "-------  -----  ------"


def test_numbers_are_formatted_to_the_column_places() -> None:
    lines = build().render().splitlines()
    assert lines[2] == "HT-04      2      14.2"
    assert lines[3] == "HT-11      3       7.0"


def test_none_renders_as_a_dash() -> None:
    table = Table(columns=[Column("a"), Column("b", places=1)])
    table.add("x", None)
    assert table.render().splitlines()[-1] == "x  -"


def test_an_empty_table_says_so() -> None:
    table = Table(columns=[Column("furnace")])
    assert table.is_empty
    assert "(no rows)" in table.render()


def test_title_is_underlined() -> None:
    table = build()
    table.title = "survey register"
    lines = table.render().splitlines()
    assert lines[0] == "survey register"
    assert lines[1] == "==============="


def test_a_row_of_the_wrong_length_is_refused() -> None:
    table = Table(columns=[Column("a"), Column("b")])
    with pytest.raises(ValidationError):
        table.add("only one")


def test_extend_adds_many_rows() -> None:
    table = Table(columns=[Column("a"), Column("b")])
    table.extend([["1", "2"], ["3", "4"]])
    assert len(table.rows) == 2


def test_an_explicit_width_truncates_with_a_tilde() -> None:
    table = Table(columns=[Column("name", width=6)])
    table.add("a very long furnace name")
    assert table.render().splitlines()[-1] == "a ver~"


def test_a_width_of_one_truncates_without_room_for_the_marker() -> None:
    table = Table(columns=[Column("n", width=1)])
    table.add("abcd")
    assert table.render().splitlines()[-1] == "a"


def test_column_validation() -> None:
    with pytest.raises(ValidationError):
        Column("a", width=0)
    with pytest.raises(ValidationError):
        Column("a", places=-1)


def test_trailing_whitespace_is_stripped() -> None:
    table = Table(columns=[Column("a"), Column("b")])
    table.add("x", "y")
    for line in table.render().splitlines():
        assert line == line.rstrip()


def test_render_kv_aligns_the_labels() -> None:
    block = render_kv([("furnace", "HT-04"), ("instrumentation", "D")])
    assert block.splitlines() == [
        "furnace          HT-04",
        "instrumentation  D",
    ]


def test_render_kv_handles_a_title_and_none() -> None:
    block = render_kv([("a", None)], title="header")
    assert block.splitlines() == ["header", "======", "a  -"]


def test_render_kv_of_nothing() -> None:
    assert render_kv([]) == ""
    assert render_kv([], title="header") == "header"


def test_str_is_the_render() -> None:
    table = build()
    assert str(table) == table.render()
