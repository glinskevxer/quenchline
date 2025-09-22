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
