from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_VALIDATION, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-04-01", *args]
        )

    return invoke


def seed_sensor(cli: Callable[..., Result], calibrated: bool = True) -> None:
    cli("sensor", "add", "TC-01", "--type", "N", "--role", "survey")
    if calibrated:
        cli(
            "sensor",
            "calibrate",
            "TC-01",
            "--number",
            "C-25-001",
            "--issued",
            "2025-01-10",
            "--point",
            "600:1.0",
            "--point",
            "1700:2.0",
            "--convention",
            "correction",
        )


def test_the_schedule_prints_with_nothing_in_it(cli: Callable[..., Result]) -> None:
    result = cli("report", "schedule")
    assert result.exit_code == 0
    assert "schedule summary" in result.output
    assert "items              0" in result.output


def test_the_schedule_lists_a_sensor_due(cli: Callable[..., Result]) -> None:
    seed_sensor(cli)
    result = cli("report", "schedule")
    assert "TC-00001" in result.output
    assert "sensor_calibration" in result.output


def test_an_uncalibrated_sensor_shows_as_never_done(cli: Callable[..., Result]) -> None:
    seed_sensor(cli, calibrated=False)
    result = cli("report", "schedule")
    assert "never_done" in result.output


def test_the_attention_flag_trims_the_board(cli: Callable[..., Result]) -> None:
    seed_sensor(cli)
    result = cli("report", "schedule", "--attention")
    assert "(no rows)" in result.output


def test_grace_softens_the_board(cli: Callable[..., Result]) -> None:
    seed_sensor(cli, calibrated=False)
    strict = cli("report", "schedule")
    assert "needing attention  1" in strict.output
    lenient = cli("report", "schedule", "--grace", "400")
    assert "needing attention  1" in lenient.output


def test_compliance_is_satisfied_on_an_empty_shop(cli: Callable[..., Result]) -> None:
    result = cli("report", "compliance")
    assert "overall     satisfied" in result.output
    assert "compliance summary" in result.output


def test_an_uncalibrated_sensor_is_a_compliance_exception(cli: Callable[..., Result]) -> None:
    seed_sensor(cli, calibrated=False)
    result = cli("report", "compliance")
    assert "overall     exception" in result.output
    assert "TC-00001" in result.output


def test_an_old_open_ncr_is_an_exception(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "load",
        "--reference",
        "L25-0001",
        "--summary",
        "soak short",
        "--on",
        "2024-01-01",
    )
    result = cli("report", "compliance")
    assert "no nonconformance older than the limit" in result.output
    assert "overall     exception" in result.output


def test_the_ncr_age_limit_can_be_moved(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "load",
        "--reference",
        "L25-0001",
        "--summary",
        "soak short",
        "--on",
        "2025-03-01",
    )
    assert "overall     satisfied" in cli("report", "compliance").output
    tight = cli("report", "compliance", "--ncr-age-limit", "10")
    assert "overall     exception" in tight.output


def test_performance_prints_the_numbers(cli: Callable[..., Result]) -> None:
    result = cli("report", "performance", "--from", "2025-01-01", "--to", "2025-03-31")
    assert "shop performance" in result.output
    assert "loads                0" in result.output


def test_performance_can_compare_two_periods(cli: Callable[..., Result]) -> None:
    result = cli(
        "report",
        "performance",
        "--from",
        "2025-01-01",
        "--to",
        "2025-03-31",
        "--against",
        "2024-10-01",
    )
    assert "period on period" in result.output


def test_a_backwards_period_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("report", "performance", "--from", "2025-03-31", "--to", "2025-01-01")
    assert result.exit_code == EXIT_VALIDATION


def test_throughput_reports_nothing_when_nothing_shipped(cli: Callable[..., Result]) -> None:
    result = cli("report", "throughput", "--from", "2025-01-01", "--to", "2025-03-31")
    assert "0 certified load(s)" in result.output


def test_throughput_refuses_a_backwards_window(cli: Callable[..., Result]) -> None:
    result = cli("report", "throughput", "--from", "2025-03-31", "--to", "2025-01-01")
    assert result.exit_code == EXIT_VALIDATION


def test_open_work_counts_the_three_piles(cli: Callable[..., Result]) -> None:
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
    cli(
        "ncr",
        "raise",
        "--subject",
        "load",
        "--reference",
        "L25-0001",
        "--summary",
        "soak short",
    )
    result = cli("report", "open-work")
    assert "on the floor: 1" in result.output
    assert "open nonconformances: 1" in result.output
    assert "L25-0001 charged" in result.output


def seed_sat(cli: Callable[..., Result], on: str = "2025-03-01") -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    cli(
        "sat",
        "record",
        "HT-04",
        "--number",
        "SAT-25-001",
        "--setpoint",
        "1550F",
        "--system",
        "1552",
        "--probe",
        "1550",
        "--system-sensor",
        "TC-01",
        "--test-sensor",
        "TC-99",
        "--on",
        on,
    )


def test_the_board_carries_the_accuracy_tests(cli: Callable[..., Result]) -> None:
    seed_sat(cli)
    result = cli("report", "schedule")
    assert "system_accuracy_test" in result.output
    assert "HT-04" in result.output


def test_a_furnace_never_tested_shows_on_the_board(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-11", "--class", "3", "--instrumentation", "D")
    result = cli("report", "schedule")
    assert "system_accuracy_test" in result.output
    assert "never_done" in result.output


def test_an_overdue_accuracy_test_breaks_compliance(cli: Callable[..., Result]) -> None:
    seed_sat(cli, on="2024-06-01")
    result = cli("report", "compliance")
    assert "system accuracy tests in date" in result.output
    assert "overall     exception" in result.output


def test_a_recent_accuracy_test_satisfies_compliance(cli: Callable[..., Result]) -> None:
    seed_sat(cli, on="2025-03-20")
    result = cli("report", "compliance")
    assert "overall     satisfied" in result.output


def test_an_accuracy_test_outranks_a_sensor_on_the_board(cli: Callable[..., Result]) -> None:
    seed_sat(cli, on="2024-06-01")
    seed_sensor(cli, calibrated=False)
    result = cli("report", "schedule", "--attention")
    rows = [
        line
        for line in result.output.splitlines()
        if line.startswith(("system_accuracy_test", "sensor_calibration"))
    ]
    assert rows[0].startswith("sensor_calibration")
