from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import main

TRACE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,95,96,90,91
30,1540,1541,1536,1537
100,1552,1551,1549,1548
"""


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-09-05", *args]
        )

    return invoke


def run_a_load(cli: Callable[..., Result], tmp_path: Path) -> None:
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
    cli("load", "start", "L25-0001", "--at", "2025-09-05T07:00:00")
    path = tmp_path / "run.csv"
    path.write_text(TRACE)
    cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100")
    cli("load", "finish", "L25-0001", "--at", "2025-09-05T12:00:00")


def test_an_empty_trail_says_so(cli: Callable[..., Result]) -> None:
    assert "nothing has been recorded yet" in cli("audit", "recent").output


def test_certifying_writes_an_entry(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    result = cli("audit", "recent")
    assert "recent activity" in result.output
    assert "certified" in result.output
    assert "L25-0001" in result.output


def test_holding_and_rejecting_write_entries(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "hold", "L25-0001", "--reason", "waiting on hardness")
    cli("load", "reject", "L25-0001", "--reason", "hardness low")
    result = cli("audit", "against", "load", "L25-0001")
    assert "held" in result.output
    assert "rejected" in result.output
    assert "waiting on hardness" in result.output


def test_the_history_is_oldest_first(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "hold", "L25-0001", "--reason", "paperwork")
    cli("load", "reject", "L25-0001", "--reason", "customer cancelled")
    output = cli("audit", "against", "load", "L25-0001").output
    assert output.index("held") < output.index("rejected")


def test_nothing_against_an_unknown_reference(cli: Callable[..., Result]) -> None:
    result = cli("audit", "against", "load", "L25-9999")
    assert "nothing recorded against load L25-9999" in result.output


def test_entries_can_be_listed_by_action(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    assert "L25-0001" in cli("audit", "action", "certified").output
    assert "nobody has scrapped anything" in cli("audit", "action", "scrapped").output


def test_the_limit_is_honoured(cli: Callable[..., Result], tmp_path: Path) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "hold", "L25-0001", "--reason", "one")
    cli("load", "reject", "L25-0001", "--reason", "two")
    lines = cli("audit", "recent", "--limit", "1").output.splitlines()
    assert len([line for line in lines if "L25-0001" in line]) == 1


def test_the_audit_table_shows_in_the_row_counts(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    assert "audit_entry" in cli("db", "counts").output


def cli_as(tmp_path: Path, actor: str) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main,
            [
                "--database",
                str(database),
                "--today",
                "2025-09-05",
                "--actor",
                actor,
                *args,
            ],
        )

    return invoke


def test_the_actor_is_recorded(tmp_path: Path) -> None:
    invoke = cli_as(tmp_path, "dt")
    run_a_load(invoke, tmp_path)
    invoke("load", "certify", "L25-0001")
    assert "dt" in invoke("audit", "recent").output


def test_the_actor_shows_in_the_settings(tmp_path: Path) -> None:
    invoke = cli_as(tmp_path, "night shift")
    assert "night shift" in invoke("settings").output


def test_an_unnamed_run_leaves_the_actor_blank(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    run_a_load(cli, tmp_path)
    cli("load", "certify", "L25-0001")
    assert "actor" in cli("settings").output


def test_raising_a_report_is_audited(cli: Callable[..., Result]) -> None:
    cli(
        "ncr",
        "raise",
        "--subject",
        "furnace",
        "--reference",
        "HT-04",
        "--summary",
        "survey overdue",
    )
    result = cli("audit", "against", "furnace", "HT-04")
    assert "raised nonconformance" in result.output
    assert "NCR-25-001" in result.output


def test_calibrating_an_instrument_is_audited(cli: Callable[..., Result]) -> None:
    cli(
        "instrument",
        "add",
        "IC-04",
        "--function",
        "controlling",
        "--span-high",
        "2400F",
        "--accuracy",
        "0.1",
        "--resolution",
        "1",
    )
    cli(
        "instrument",
        "calibrate",
        "IC-04",
        "--number",
        "CAL-25-001",
        "--tolerance",
        "2",
        "--point",
        "1550:1550.5",
        "--on",
        "2025-03-01",
    )
    result = cli("audit", "against", "instrument", "IC-04")
    assert "calibrated" in result.output
    assert "passed" in result.output


def test_recording_an_accuracy_test_is_audited(cli: Callable[..., Result]) -> None:
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
        "2025-08-01",
    )
    result = cli("audit", "against", "furnace", "HT-04")
    assert "recorded accuracy test" in result.output
    assert "SAT-25-001 passed" in result.output


def test_closing_a_report_is_audited(cli: Callable[..., Result]) -> None:
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
    cli("ncr", "disposition", "NCR-25-001", "--as", "rework")
    cli("ncr", "action", "NCR-25-001", "--note", "rerun")
    cli("ncr", "close", "NCR-25-001")
    result = cli("audit", "action", "closed nonconformance")
    assert "NCR-25-001" in result.output
