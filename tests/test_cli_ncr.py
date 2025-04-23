from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_STATE, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-04-01", *args]
        )

    return invoke


def raise_load_ncr(cli: Callable[..., Result]) -> Result:
    return cli(
        "ncr",
        "raise",
        "--subject",
        "load",
        "--reference",
        "L25-0001",
        "--summary",
        "soak short by twelve minutes",
    )


def test_a_report_is_numbered_automatically(cli: Callable[..., Result]) -> None:
    result = raise_load_ncr(cli)
    assert result.exit_code == 0
    assert "NCR-25-001" in result.output
    second = raise_load_ncr(cli)
    assert "NCR-25-002" in second.output


def test_a_number_can_be_given(cli: Callable[..., Result]) -> None:
    result = cli(
        "ncr",
        "raise",
        "--subject",
        "furnace",
        "--reference",
        "HT-04",
        "--summary",
        "survey overdue",
        "--number",
        "NCR-25-099",
    )
    assert "NCR-25-099" in result.output


def test_the_lifecycle_runs_in_order(cli: Callable[..., Result]) -> None:
    raise_load_ncr(cli)
    assert cli("ncr", "close", "NCR-25-001").exit_code == EXIT_STATE
    assert cli("ncr", "disposition", "NCR-25-001", "--as", "rework").exit_code == 0
    assert cli("ncr", "action", "NCR-25-001", "--note", "rerun").exit_code == 0
    assert cli("ncr", "close", "NCR-25-001").exit_code == 0


def test_an_equipment_report_cannot_close_without_a_window(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "instrument",
        "--reference",
        "IC-04",
        "--summary",
        "found out of tolerance",
    )
    cli("ncr", "disposition", "NCR-25-001", "--as", "review")
    cli("ncr", "action", "NCR-25-001", "--note", "recalibrated")
    assert cli("ncr", "close", "NCR-25-001").exit_code == EXIT_STATE


def test_the_window_lets_it_close(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "instrument",
        "--reference",
        "IC-04",
        "--summary",
        "found out of tolerance",
    )
    window = cli("ncr", "window", "NCR-25-001", "--from", "2024-10-01", "--to", "2025-04-01")
    assert "covers 0 load(s)" in window.output
    cli("ncr", "disposition", "NCR-25-001", "--as", "review")
    cli("ncr", "action", "NCR-25-001", "--note", "recalibrated")
    assert cli("ncr", "close", "NCR-25-001").exit_code == 0


def test_a_window_catches_a_finished_load(cli: Callable[..., Result]) -> None:
    cli(
        "load",
        "plan",
        "L25-0001",
        "--work-order",
        "W104417",
        "--furnace",
        "HT-04",
        "--recipe",
        "HT-4140-Q",
        "--revision",
        "C",
    )
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-02-01T07:00:00")
    cli("load", "hold", "L25-0001", "--reason", "paperwork")
    cli(
        "ncr",
        "raise",
        "--subject",
        "instrument",
        "--reference",
        "IC-04",
        "--summary",
        "out of tolerance",
    )
    result = cli("ncr", "window", "NCR-25-001", "--from", "2025-01-01", "--to", "2025-04-01")
    assert "covers 0 load(s)" in result.output


def test_listing_and_filtering(cli: Callable[..., Result]) -> None:
    raise_load_ncr(cli)
    cli("ncr", "disposition", "NCR-25-001", "--as", "rework")
    cli("ncr", "action", "NCR-25-001", "--note", "rerun")
    cli("ncr", "close", "NCR-25-001")
    raise_load_ncr(cli)
    everything = cli("ncr", "list")
    assert "NCR-25-001" in everything.output
    assert "NCR-25-002" in everything.output
    open_only = cli("ncr", "list", "--open")
    assert "NCR-25-002" in open_only.output


def test_in_doubt_says_so_when_nothing_is(cli: Callable[..., Result]) -> None:
    raise_load_ncr(cli)
    assert "no open report throws any load into doubt" in cli("ncr", "in-doubt").output


def test_in_doubt_lists_the_reports_with_windows(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "sensor",
        "--reference",
        "TC-00001",
        "--summary",
        "drifted",
    )
    cli("ncr", "window", "NCR-25-001", "--from", "2024-10-01", "--to", "2025-04-01")
    result = cli("ncr", "in-doubt")
    assert "work in doubt" in result.output
    assert "NCR-25-001" in result.output


def test_show_prints_the_report(cli: Callable[..., Result]) -> None:
    raise_load_ncr(cli)
    result = cli("ncr", "show", "NCR-25-001")
    assert "nonconformance" in result.output
    assert "soak short by twelve minutes" in result.output
    assert "age" in result.output


def test_show_of_an_unknown_report(cli: Callable[..., Result]) -> None:
    assert cli("ncr", "show", "NCR-25-999").exit_code == EXIT_NOT_FOUND
