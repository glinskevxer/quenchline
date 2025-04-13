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


def add_survey_couple(cli: Callable[..., Result], tag: str = "TC-01") -> Result:
    return cli("sensor", "add", tag, "--type", "N", "--role", "survey")


def calibrate(
    cli: Callable[..., Result], tag: str = "TC-01", issued: str = "2025-01-10"
) -> Result:
    return cli(
        "sensor",
        "calibrate",
        tag,
        "--number",
        "C-25-001",
        "--issued",
        issued,
        "--point",
        "600:1.0",
        "--point",
        "1700:2.0",
        "--convention",
        "correction",
    )


def test_a_couple_can_be_added(cli: Callable[..., Result]) -> None:
    result = add_survey_couple(cli)
    assert result.exit_code == 0
    assert "added TC-00001 type N survey" in result.output


def test_the_reserved_serial_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("sensor", "add", "TC-0", "--type", "N", "--role", "survey")
    assert result.exit_code == EXIT_VALIDATION


def test_an_expendable_control_couple_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "sensor",
        "add",
        "TC-02",
        "--type",
        "K",
        "--role",
        "control",
        "--construction",
        "expendable",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_adding_twice_conflicts(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    assert add_survey_couple(cli).exit_code == EXIT_CONFLICT


def test_calibration_reports_the_due_date(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    result = calibrate(cli)
    assert result.exit_code == 0
    assert "due 2026-01-10" in result.output


def test_a_noble_couple_gets_two_years(cli: Callable[..., Result]) -> None:
    cli("sensor", "add", "TC-05", "--type", "S", "--role", "survey")
    result = calibrate(cli, "TC-05")
    assert "due 2027-01-10" in result.output


def test_a_bad_point_is_refused(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    result = cli(
        "sensor",
        "calibrate",
        "TC-01",
        "--number",
        "C-25-001",
        "--issued",
        "2025-01-10",
        "--point",
        "six hundred",
        "--convention",
        "correction",
    )
    assert result.exit_code != 0


def test_calibrating_an_unknown_couple(cli: Callable[..., Result]) -> None:
    assert calibrate(cli, "TC-99").exit_code == EXIT_NOT_FOUND


def test_the_register_prints(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    calibrate(cli)
    result = cli("sensor", "list")
    assert "sensor register summary" in result.output
    assert "thermocouple register" in result.output
    assert "TC-00001" in result.output


def test_eligibility_explains_a_refusal(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    result = cli("sensor", "eligible", "--role", "survey", "--at", "1550F")
    assert "refused" in result.output
    assert "no calibration certificate" in result.output


def test_eligibility_after_calibration(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    calibrate(cli)
    result = cli("sensor", "eligible", "--role", "survey", "--at", "1550F")
    assert "eligible" in result.output


def test_booking_a_run_reports_the_life_left(cli: Callable[..., Result]) -> None:
    cli(
        "sensor",
        "add",
        "TC-07",
        "--type",
        "K",
        "--role",
        "load",
        "--construction",
        "expendable",
    )
    result = cli(
        "sensor",
        "use",
        "TC-07",
        "--on",
        "2025-03-01",
        "--peak",
        "1250F",
        "--hours",
        "2",
    )
    assert result.exit_code == 0
    assert "used 1 of 1 allowed" in result.output


def test_show_reports_the_life_and_tolerance(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    calibrate(cli)
    result = cli("sensor", "show", "TC-01")
    assert "thermocouple TC-00001" in result.output
    assert "C-25-001" in result.output
    assert "tolerance at 1550 F" in result.output


def test_show_of_an_unknown_couple(cli: Callable[..., Result]) -> None:
    assert cli("sensor", "show", "TC-99").exit_code == EXIT_NOT_FOUND


def test_scrapping_records_the_reason(cli: Callable[..., Result]) -> None:
    add_survey_couple(cli)
    result = cli("sensor", "scrap", "TC-01", "--reason", "bead let go")
    assert "scrapped: bead let go" in result.output
    listed = cli("sensor", "list")
    assert "scrapped" in listed.output
