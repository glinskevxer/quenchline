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
            main, ["--database", str(database), "--today", "2025-08-15", *args]
        )

    return invoke


def add(cli: Callable[..., Result], tag: str = "IC-04", **flags: str) -> Result:
    args = [
        "instrument",
        "add",
        tag,
        "--function",
        flags.get("function", "controlling"),
        "--span-high",
        "2400F",
        "--accuracy",
        flags.get("accuracy", "0.1"),
        "--resolution",
        flags.get("resolution", "1"),
        "--make",
        "Eurotherm",
        "--model",
        "3216",
    ]
    if "readout" in flags:
        args.extend(["--readout", flags["readout"]])
    return cli(*args)


def calibrate(
    cli: Callable[..., Result],
    number: str = "CAL-25-001",
    point: str = "1550:1550.5",
    on: str = "2025-03-01",
) -> Result:
    return cli(
        "instrument",
        "calibrate",
        "IC-04",
        "--number",
        number,
        "--tolerance",
        "2",
        "--point",
        point,
        "--on",
        on,
    )


def test_an_instrument_can_be_added(cli: Callable[..., Result]) -> None:
    result = add(cli)
    assert result.exit_code == 0
    assert "added IC-04 controlling" in result.output


def test_adding_twice_conflicts(cli: Callable[..., Result]) -> None:
    add(cli)
    assert add(cli).exit_code == EXIT_CONFLICT


def test_a_zero_accuracy_is_refused(cli: Callable[..., Result]) -> None:
    assert add(cli, accuracy="0").exit_code == EXIT_VALIDATION


def test_a_clean_calibration_passes(cli: Callable[..., Result]) -> None:
    add(cli)
    result = calibrate(cli)
    assert result.exit_code == 0
    assert "CAL-25-001 on IC-04: passed" in result.output
    assert "work in doubt" not in result.output


def test_an_adjusted_calibration_names_the_window(cli: Callable[..., Result]) -> None:
    add(cli)
    calibrate(cli, "CAL-25-001", "1550:1550.5", "2025-01-10")
    result = calibrate(cli, "CAL-25-002", "1550:1556:1550.2", "2025-07-01")
    assert "adjusted" in result.output
    assert "work in doubt from 2025-01-10 to 2025-07-01" in result.output


def test_a_calibration_that_cannot_be_brought_in_fails(cli: Callable[..., Result]) -> None:
    add(cli)
    result = calibrate(cli, "CAL-25-001", "1550:1556:1554")
    assert result.exit_code == EXIT_VALIDATION
    assert "cannot be brought inside tolerance" in result.output


def test_a_malformed_point_is_refused(cli: Callable[..., Result]) -> None:
    add(cli)
    assert calibrate(cli, "CAL-25-001", "1550").exit_code != 0
    assert calibrate(cli, "CAL-25-002", "1550:hot").exit_code != 0


def test_calibrating_an_unknown_instrument(cli: Callable[..., Result]) -> None:
    assert calibrate(cli).exit_code == EXIT_NOT_FOUND


def test_the_register_shows_the_due_date(cli: Callable[..., Result]) -> None:
    add(cli)
    calibrate(cli)
    result = cli("instrument", "list")
    assert "instruments" in result.output
    assert "2025-09-01" in result.output
    assert "in date" in result.output


def test_an_overdue_instrument_says_so(cli: Callable[..., Result]) -> None:
    add(cli)
    calibrate(cli, on="2024-01-01")
    assert "overdue" in cli("instrument", "list").output


def test_show_reports_what_it_is_good_enough_for(cli: Callable[..., Result]) -> None:
    add(cli)
    result = cli("instrument", "show", "IC-04")
    assert "instrument       IC-04" in result.output
    assert "controlling" in result.output
    assert "never calibrated" in result.output


def test_an_analogue_instrument_cannot_be_field_test_kit(cli: Callable[..., Result]) -> None:
    add(cli, readout="analogue")
    result = cli("instrument", "show", "IC-04")
    assert "field_test" not in result.output.split("good enough for")[1]


def test_a_coarse_instrument_is_good_for_nothing(cli: Callable[..., Result]) -> None:
    add(cli, resolution="9")
    result = cli("instrument", "show", "IC-04")
    assert "nothing" in result.output


def test_show_of_an_unknown_instrument(cli: Callable[..., Result]) -> None:
    assert cli("instrument", "show", "IC-09").exit_code == EXIT_NOT_FOUND


def test_instruments_appear_on_the_schedule_board(cli: Callable[..., Result]) -> None:
    add(cli)
    calibrate(cli)
    result = cli("report", "schedule")
    assert "instrument_calibration" in result.output
    assert "IC-04" in result.output


def test_an_overdue_instrument_breaks_compliance(cli: Callable[..., Result]) -> None:
    add(cli)
    calibrate(cli, on="2024-01-01")
    result = cli("report", "compliance")
    assert "instruments calibrated" in result.output
    assert "overall     exception" in result.output
