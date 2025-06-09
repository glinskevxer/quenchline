from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_VALIDATION, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-06-10", *args]
        )

    return invoke


def commission(cli: Callable[..., Result], tag: str = "HT-04", cls: str = "3") -> None:
    cli("furnace", "add", tag, "--class", cls, "--instrumentation", "D")


def record(
    cli: Callable[..., Result],
    number: str = "SAT-25-001",
    system: str = "1552",
    on: str = "2025-06-01",
    furnace: str = "HT-04",
    *extra: str,
) -> Result:
    return cli(
        "sat",
        "record",
        furnace,
        "--number",
        number,
        "--setpoint",
        "1550F",
        "--system",
        system,
        "--probe",
        "1550",
        "--system-sensor",
        "TC-01",
        "--test-sensor",
        "TC-99",
        "--on",
        on,
        *extra,
    )


def test_a_passing_test_is_recorded(cli: Callable[..., Result]) -> None:
    commission(cli)
    result = record(cli)
    assert result.exit_code == 0
    assert "SAT-25-001 passed" in result.output


def test_a_failing_test_reports_the_window(cli: Callable[..., Result]) -> None:
    commission(cli)
    record(cli, "SAT-25-001", "1552", "2025-03-01")
    result = record(cli, "SAT-25-002", "1570", "2025-06-01")
    assert result.exit_code == EXIT_VALIDATION
    assert "system accuracy test failure" in result.output
    assert "work in doubt from  2025-03-01" in result.output


def test_a_failing_test_is_still_stored(cli: Callable[..., Result]) -> None:
    commission(cli)
    record(cli, "SAT-25-001", "1570")
    result = cli("sat", "history", "HT-04")
    assert "SAT-25-001" in result.output
    assert "failed" in result.output


def test_the_class_decides_the_verdict(cli: Callable[..., Result]) -> None:
    commission(cli, "HT-11", "1")
    result = record(cli, "SAT-25-003", "1554", "2025-06-01", "HT-11")
    assert result.exit_code == EXIT_VALIDATION


def test_a_loose_furnace_takes_the_same_reading(cli: Callable[..., Result]) -> None:
    commission(cli, "HT-06", "6")
    result = record(cli, "SAT-25-004", "1554", "2025-06-01", "HT-06")
    assert result.exit_code == 0


def test_recording_against_an_unknown_furnace(cli: Callable[..., Result]) -> None:
    assert record(cli).exit_code == EXIT_NOT_FOUND


def test_a_near_miss_is_noted(cli: Callable[..., Result]) -> None:
    commission(cli)
    result = record(cli, "SAT-25-005", "1556")
    assert "note: passed on less than a tenth of the allowance" in result.output


def test_uncorrected_testing_is_noted_and_tightens_the_limit(
    cli: Callable[..., Result],
) -> None:
    commission(cli)
    result = record(cli, "SAT-25-006", "1554", "2025-06-01", "HT-04", "--raw")
    assert "note: corrections not applied" in result.output


def test_an_uncorrected_test_can_fail_where_a_corrected_one_passed(
    cli: Callable[..., Result],
) -> None:
    commission(cli)
    assert record(cli, "SAT-25-007", "1555").exit_code == 0
    raw = record(cli, "SAT-25-008", "1555", "2025-06-02", "HT-04", "--raw")
    assert raw.exit_code == EXIT_VALIDATION


def test_the_history_summarises_the_run(cli: Callable[..., Result]) -> None:
    commission(cli)
    record(cli, "SAT-25-001", "1552", "2025-03-01")
    record(cli, "SAT-25-002", "1551", "2025-04-01")
    result = cli("sat", "history", "HT-04")
    assert "sat summary" in result.output
    assert "consecutive passes  2" in result.output
    assert "tests on file       2" in result.output


def test_a_run_of_passes_stretches_the_interval(cli: Callable[..., Result]) -> None:
    commission(cli)
    for index in range(4):
        record(cli, f"SAT-25-01{index}", "1551", f"2025-0{index + 1}-01")
    result = cli("sat", "history", "HT-04")
    assert "interval            2 months" in result.output


def test_the_due_board_lists_every_furnace(cli: Callable[..., Result]) -> None:
    commission(cli, "HT-04")
    commission(cli, "HT-11")
    record(cli, "SAT-25-001", "1552", "2025-06-01")
    result = cli("sat", "due")
    assert "system accuracy tests due" in result.output
    assert "HT-11" in result.output
    assert "never tested" in result.output


def test_the_due_board_says_so_with_no_furnaces(cli: Callable[..., Result]) -> None:
    assert "no furnaces on the register" in cli("sat", "due").output


def test_grace_moves_a_furnace_back_into_date(cli: Callable[..., Result]) -> None:
    commission(cli)
    record(cli, "SAT-25-001", "1552", "2025-01-01")
    assert "overdue" in cli("sat", "due").output
    assert "in date" in cli("sat", "due", "--grace", "200").output
