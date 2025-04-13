from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_STATE, EXIT_VALIDATION, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-04-01", *args]
        )

    return invoke


def plan(cli: Callable[..., Result], lot: str = "L25-0001") -> Result:
    return cli(
        "load",
        "plan",
        lot,
        "--work-order",
        "W104417",
        "--furnace",
        "HT-04",
        "--recipe",
        "HT-4140-Q",
        "--revision",
        "C",
        "--weight",
        "1450lb",
        "--part",
        "PN-8891:40:4140",
    )


def test_a_load_can_be_planned(cli: Callable[..., Result]) -> None:
    result = plan(cli)
    assert result.exit_code == 0
    assert "planned L25-0001 on HT-04 to HT-4140-Q rev C" in result.output


def test_a_bad_part_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
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
        "--part",
        "PN-8891",
    )
    assert result.exit_code != 0


def test_a_bad_quantity_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
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
        "--part",
        "PN-8891:lots",
    )
    assert result.exit_code != 0


def test_the_states_run_in_order(cli: Callable[..., Result]) -> None:
    plan(cli)
    charged = cli("load", "charge", "L25-0001", "--sensor", "TC-01", "--sensor", "TC-02")
    assert "charged with 2 load sensor(s)" in charged.output
    started = cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    assert "running" in started.output


def test_a_load_cannot_start_before_it_is_charged(cli: Callable[..., Result]) -> None:
    plan(cli)
    assert cli("load", "start", "L25-0001").exit_code == EXIT_STATE


def test_finishing_without_a_trace_is_refused(cli: Callable[..., Result]) -> None:
    plan(cli)
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    result = cli("load", "finish", "L25-0001", "--at", "2025-04-01T12:00:00")
    assert result.exit_code == EXIT_VALIDATION
    assert "attach a trace" in result.output


def test_a_bad_time_is_refused(cli: Callable[..., Result]) -> None:
    plan(cli)
    result = cli("load", "charge", "L25-0001", "--at", "this morning")
    assert result.exit_code == EXIT_VALIDATION


def test_holding_records_the_reason(cli: Callable[..., Result]) -> None:
    plan(cli)
    result = cli("load", "hold", "L25-0001", "--reason", "furnace survey overdue")
    assert "held: furnace survey overdue" in result.output


def test_rejecting_needs_the_load_to_be_finished(cli: Callable[..., Result]) -> None:
    plan(cli)
    assert cli("load", "reject", "L25-0001", "--reason", "no").exit_code == EXIT_STATE


def test_a_held_load_can_be_rejected(cli: Callable[..., Result]) -> None:
    plan(cli)
    cli("load", "hold", "L25-0001", "--reason", "waiting")
    result = cli("load", "reject", "L25-0001", "--reason", "customer cancelled")
    assert "rejected: customer cancelled" in result.output


def test_listing_and_filtering(cli: Callable[..., Result]) -> None:
    plan(cli, "L25-0001")
    plan(cli, "L25-0002")
    cli("load", "charge", "L25-0002")
    assert "L25-0001" in cli("load", "list").output
    charged = cli("load", "list", "--state", "charged")
    assert "L25-0002" in charged.output
    assert "L25-0001" not in charged.output
    assert "L25-0001" in cli("load", "list", "--furnace", "HT-04").output


def test_the_floor_is_empty_until_something_is_charged(cli: Callable[..., Result]) -> None:
    plan(cli)
    assert "nothing on the floor" in cli("load", "floor").output
    cli("load", "charge", "L25-0001")
    assert "L25-0001 charged on HT-04" in cli("load", "floor").output


def test_show_prints_the_traveller(cli: Callable[..., Result]) -> None:
    plan(cli)
    result = cli("load", "show", "L25-0001")
    assert "load record" in result.output
    assert "PN-8891" in result.output
    assert "1450.0 lb" in result.output


def test_show_of_an_unknown_load(cli: Callable[..., Result]) -> None:
    assert cli("load", "show", "L25-9999").exit_code == EXIT_NOT_FOUND
