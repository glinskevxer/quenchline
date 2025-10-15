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
    assert result.exit_code == EXIT_STATE
    assert "attach the logger file" in result.output


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


GOOD_TRACE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,100,101,95,96
30,1545,1546,1538,1539
60,1552,1551,1549,1548
"""


def test_a_trace_can_be_attached(cli: Callable[..., Result], tmp_path: Path) -> None:
    plan(cli)
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(GOOD_TRACE)
    result = cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    assert result.exit_code == 0
    assert "carries run.csv" in result.output
    assert "3 row(s) over 4 channel(s)" in result.output


def test_the_same_file_cannot_go_on_two_loads(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    plan(cli, "L25-0001")
    plan(cli, "L25-0002")
    path = tmp_path / "run.csv"
    path.write_text(GOOD_TRACE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    again = cli("load", "attach", "L25-0002", str(path), "--profile", "eurotherm 6100")
    assert again.exit_code == EXIT_VALIDATION
    assert "already on load L25-0001" in again.output


def test_reattaching_the_same_file_to_the_same_load_is_fine(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    plan(cli)
    path = tmp_path / "run.csv"
    path.write_text(GOOD_TRACE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    again = cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    assert again.exit_code == 0


def test_a_junk_file_is_refused(cli: Callable[..., Result], tmp_path: Path) -> None:
    plan(cli)
    path = tmp_path / "run.csv"
    path.write_text("Elapsed (min),Channel 1\n0,100\n")
    result = cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    assert result.exit_code == EXIT_VALIDATION


def test_finishing_works_once_a_trace_is_attached(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    plan(cli)
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(GOOD_TRACE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    result = cli("load", "finish", "L25-0001", "--at", "2025-04-01T12:00:00")
    assert result.exit_code == 0
    assert "complete" in result.output


GOOD_CYCLE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,95,96,90,91
30,1540,1541,1536,1537
100,1552,1551,1549,1548
"""

SHORT_CYCLE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,95,96,90,91
30,1540,1541,1536,1537
55,1552,1551,1549,1548
"""


def write_recipe(cli: Callable[..., Result], load_sensors: str = "0") -> None:
    cli(
        "recipe",
        "add",
        "HT-4140-Q",
        "--revision",
        "C",
        "--title",
        "4140 harden",
        "--load-sensors",
        load_sensors,
        "--step",
        "ramp:heat:setpoint=1550F,max_rate=4000",
        "--step",
        "soak:austenitise:setpoint=1550F,band=25,minimum=1h",
    )
    cli("recipe", "release", "HT-4140-Q", "--revision", "C")


def run_with(cli: Callable[..., Result], tmp_path: Path, text: str) -> Result:
    plan(cli)
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(text)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    cli("load", "finish", "L25-0001", "--at", "2025-04-01T12:00:00")
    return cli("load", "evaluate", "L25-0001")


def test_a_clean_run_is_accepted(cli: Callable[..., Result], tmp_path: Path) -> None:
    write_recipe(cli)
    result = run_with(cli, tmp_path, GOOD_CYCLE)
    assert result.exit_code == 0, result.output
    assert "run summary" in result.output
    assert "disposition  accept" in result.output
    assert "cycle steps located on the trace" in result.output


def test_a_short_soak_is_reported_and_blocks(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    write_recipe(cli)
    result = run_with(cli, tmp_path, SHORT_CYCLE)
    assert result.exit_code == EXIT_VALIDATION
    assert "short_soak" in result.output
    assert "rework" in result.output


def test_a_missing_load_sensor_is_reported(cli: Callable[..., Result], tmp_path: Path) -> None:
    write_recipe(cli, load_sensors="4")
    result = run_with(cli, tmp_path, GOOD_CYCLE)
    assert "no_load_sensor" in result.output


def test_evaluating_without_a_trace_is_refused(cli: Callable[..., Result]) -> None:
    write_recipe(cli)
    plan(cli)
    result = cli("load", "evaluate", "L25-0001")
    assert result.exit_code == EXIT_VALIDATION
    assert "no logger file attached" in result.output


def test_evaluating_against_a_missing_recipe(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    plan(cli)
    path = tmp_path / "run.csv"
    path.write_text(GOOD_CYCLE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    result = cli("load", "evaluate", "L25-0001")
    assert result.exit_code == EXIT_NOT_FOUND


def test_a_deleted_logger_file_is_reported(cli: Callable[..., Result], tmp_path: Path) -> None:
    write_recipe(cli)
    plan(cli)
    path = tmp_path / "run.csv"
    path.write_text(GOOD_CYCLE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    path.unlink()
    result = cli("load", "evaluate", "L25-0001")
    assert result.exit_code == EXIT_VALIDATION
    assert "no longer at" in result.output


def test_the_concession_policy_changes_the_disposition(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    write_recipe(cli)
    run_with(cli, tmp_path, SHORT_CYCLE)
    strict = cli("load", "evaluate", "L25-0001", "--no-concession", "--rework-limit", "0")
    assert "review" in strict.output


def test_grading_is_stored_and_reported(cli: Callable[..., Result], tmp_path: Path) -> None:
    write_recipe(cli)
    run_with(cli, tmp_path, SHORT_CYCLE)
    result = cli("report", "deviations")
    assert "graded runs       1" in result.output
    assert "short_soak" in result.output


def test_the_deviation_report_can_group_by_furnace(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    write_recipe(cli)
    run_with(cli, tmp_path, SHORT_CYCLE)
    result = cli("report", "deviations", "--furnace")
    assert "findings by furnace" in result.output
    assert "HT-04" in result.output


def test_an_ungraded_load_is_listed_as_waiting(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    write_recipe(cli)
    plan(cli)
    cli("load", "charge", "L25-0001")
    cli("load", "start", "L25-0001", "--at", "2025-04-01T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(GOOD_CYCLE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    cli("load", "finish", "L25-0001", "--at", "2025-04-01T12:00:00")
    result = cli("report", "deviations")
    assert "awaiting grading  1" in result.output
    assert "nothing has been graded yet" in result.output


def test_grading_is_audited(cli: Callable[..., Result], tmp_path: Path) -> None:
    write_recipe(cli)
    run_with(cli, tmp_path, GOOD_CYCLE)
    assert "graded" in cli("audit", "against", "load", "L25-0001").output
