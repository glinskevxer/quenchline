from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_VALIDATION, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-04-01", *args]
        )

    return invoke


def test_a_furnace_can_be_added_and_listed(cli: Callable[..., Result]) -> None:
    added = cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    assert added.exit_code == 0
    assert "added HT-04 class 3 type D" in added.output

    listed = cli("furnace", "list")
    assert "furnace register" in listed.output
    assert "HT-04" in listed.output


def test_adding_the_same_furnace_twice_conflicts(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    again = cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    assert again.exit_code == EXIT_CONFLICT


def test_a_bad_class_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("furnace", "add", "HT-04", "--class", "9", "--instrumentation", "D")
    assert result.exit_code == EXIT_VALIDATION


def test_a_bad_instrumentation_type_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "Z")
    assert result.exit_code == EXIT_VALIDATION


def test_a_zone_can_be_added(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    result = cli(
        "furnace",
        "zone",
        "HT-04",
        "main",
        "--cubic-feet",
        "40",
        "--low",
        "1000F",
        "--high",
        "1800F",
    )
    assert result.exit_code == 0
    assert "survey needs 9 sensors" in result.output


def test_a_precision_furnace_needs_more_survey_sensors(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-11", "--class", "1", "--instrumentation", "A")
    result = cli(
        "furnace",
        "zone",
        "HT-11",
        "main",
        "--cubic-feet",
        "40",
        "--low",
        "1000",
        "--high",
        "1800",
    )
    assert "survey needs 11 sensors" in result.output


def test_a_zone_on_an_unknown_furnace_is_not_found(cli: Callable[..., Result]) -> None:
    result = cli(
        "furnace",
        "zone",
        "HT-99",
        "main",
        "--cubic-feet",
        "40",
        "--low",
        "1000",
        "--high",
        "1800",
    )
    assert result.exit_code == EXIT_NOT_FOUND


def test_qualifying_sets_the_range(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    result = cli("furnace", "qualify", "HT-04", "--low", "1200", "--high", "1700")
    assert "qualified 1200 F to 1700 F" in result.output
    shown = cli("furnace", "show", "HT-04")
    assert "1200 F to 1700 F" in shown.output


def test_show_reports_the_intervals(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    result = cli("furnace", "show", "HT-04")
    assert "sat interval     1 month" in result.output
    assert "survey interval  3 months" in result.output
    assert "uniformity band  +15.0 F" in result.output


def test_show_lists_the_deficiencies(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "A")
    result = cli("furnace", "show", "HT-04")
    assert "too_few_control_sensors" in result.output


def test_show_of_an_unknown_furnace(cli: Callable[..., Result]) -> None:
    assert cli("furnace", "show", "HT-99").exit_code == EXIT_NOT_FOUND


def test_capability_lists_what_can_run(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    cli(
        "furnace",
        "zone",
        "HT-04",
        "main",
        "--cubic-feet",
        "40",
        "--low",
        "1000",
        "--high",
        "1800",
    )
    cli("furnace", "qualify", "HT-04", "--low", "1200", "--high", "1700")
    result = cli("furnace", "capability", "--at", "1550F")
    assert result.exit_code == 0
    assert "able to run    1" in result.output
    assert "HT-04" in result.output


def test_capability_with_nothing_qualified_fails(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    result = cli("furnace", "capability", "--at", "1550F")
    assert result.exit_code == EXIT_VALIDATION


def test_the_deficiency_report_lists_the_bad_ones(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "A")
    result = cli("furnace", "deficiencies")
    assert "instrumentation shortfalls" in result.output
    assert "HT-04" in result.output
