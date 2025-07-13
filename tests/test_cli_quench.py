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
            main, ["--database", str(database), "--today", "2025-07-10", *args]
        )

    return invoke


def add_oil(cli: Callable[..., Result], identifier: str = "QT-1") -> Result:
    return cli(
        "bath",
        "add",
        identifier,
        "--medium",
        "AAA fast oil",
        "--kind",
        "oil",
        "--setpoint",
        "130F",
        "--band",
        "20",
        "--gallons",
        "2000",
        "--agitation",
        "moderate",
    )


def add_polymer(cli: Callable[..., Result]) -> Result:
    return cli(
        "bath",
        "add",
        "QT-2",
        "--medium",
        "polymer 10 percent",
        "--kind",
        "polymer",
        "--setpoint",
        "100F",
        "--band",
        "15",
        "--gallons",
        "1500",
        "--concentration-low",
        "8",
        "--concentration-high",
        "12",
    )


def test_a_bath_can_be_added(cli: Callable[..., Result]) -> None:
    result = add_oil(cli)
    assert result.exit_code == 0
    assert "added QT-1 AAA fast oil at 130 F" in result.output
    assert "capacity 2000.0 lb" in result.output


def test_adding_twice_conflicts(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    assert add_oil(cli).exit_code == EXIT_CONFLICT


def test_a_zero_band_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "bath",
        "add",
        "QT-9",
        "--medium",
        "oil",
        "--kind",
        "oil",
        "--setpoint",
        "130F",
        "--band",
        "0",
        "--gallons",
        "2000",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_a_polymer_needs_its_range(cli: Callable[..., Result]) -> None:
    result = cli(
        "bath",
        "add",
        "QT-9",
        "--medium",
        "polymer",
        "--kind",
        "polymer",
        "--setpoint",
        "100F",
        "--band",
        "15",
        "--gallons",
        "1500",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_a_polymer_bath_is_added_with_its_range(cli: Callable[..., Result]) -> None:
    assert add_polymer(cli).exit_code == 0
    assert "polymer" in cli("bath", "list").output


def test_a_check_moves_the_due_date(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    result = cli("bath", "check", "QT-1", "--temperature", "135F", "--on", "2025-07-08")
    assert "checked at 135 F" in result.output
    assert "next due 2025-07-15" in result.output


def test_checking_an_unknown_bath(cli: Callable[..., Result]) -> None:
    assert cli("bath", "check", "QT-9", "--temperature", "135F").exit_code == EXIT_NOT_FOUND


def test_a_ready_bath_reports_ready(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli("bath", "check", "QT-1", "--temperature", "130F", "--on", "2025-07-08")
    result = cli("bath", "ready", "QT-1", "--weight", "1450lb")
    assert result.exit_code == 0
    assert "verdict         ready" in result.output
    assert "0.72 lb per gallon" in result.output


def test_an_unchecked_bath_is_not_ready(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    result = cli("bath", "ready", "QT-1", "--weight", "1450lb")
    assert result.exit_code == EXIT_VALIDATION
    assert "never been checked" in result.output


def test_an_overloaded_bath_is_not_ready(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli("bath", "check", "QT-1", "--temperature", "130F", "--on", "2025-07-08")
    result = cli("bath", "ready", "QT-1", "--weight", "5000lb")
    assert result.exit_code == EXIT_VALIDATION
    assert "lb per gallon against a limit" in result.output


def test_a_cold_bath_is_not_ready(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli("bath", "check", "QT-1", "--temperature", "90F", "--on", "2025-07-08")
    result = cli("bath", "ready", "QT-1", "--weight", "1450lb")
    assert "under the operating band" in result.output


def test_weak_agitation_is_not_ready(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli(
        "bath",
        "check",
        "QT-1",
        "--temperature",
        "130F",
        "--agitation",
        "mild",
        "--on",
        "2025-07-08",
    )
    result = cli("bath", "ready", "QT-1", "--weight", "1450lb")
    assert "agitation mild" in result.output


def test_grace_lets_a_stale_check_through(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli("bath", "check", "QT-1", "--temperature", "130F", "--on", "2025-06-01")
    assert cli("bath", "ready", "QT-1", "--weight", "1450lb").exit_code == EXIT_VALIDATION
    assert cli("bath", "ready", "QT-1", "--weight", "1450lb", "--grace", "60").exit_code == 0


def test_the_bath_register_prints(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    add_polymer(cli)
    result = cli("bath", "list")
    assert "quench baths" in result.output
    assert "QT-1" in result.output
    assert "QT-2" in result.output


def test_baths_appear_on_the_schedule_board(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    result = cli("report", "schedule")
    assert "bath_check" in result.output
    assert "QT-1" in result.output


def test_an_overdue_bath_check_breaks_compliance(cli: Callable[..., Result]) -> None:
    add_oil(cli)
    cli("bath", "check", "QT-1", "--temperature", "130F", "--on", "2025-05-01")
    result = cli("report", "compliance")
    assert "quench baths checked" in result.output
    assert "overall     exception" in result.output
