"""A load from an empty shop to a printed certificate, through the command line.

The unit tests cover each rule on its own. This walks the whole thing in the
order a shop would, because most of the ways this package can be wrong are ways
two correct pieces fail to meet: a tag written short at one end and long at the
other, a state that cannot be reached from where the last command left it, a
report that reads a column nothing writes.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import main

TRACE = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,95,96,90,91
20,1201,1199,1195,1196
50,1548,1546,1539,1541
110,1552,1551,1549,1548
170,1550,1549,1547,1546
"""


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-06-02", *args]
        )

    return invoke


def ok(result: Result) -> Result:
    assert result.exit_code == 0, result.output
    return result


def commission(cli: Callable[..., Result]) -> None:
    ok(cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D"))
    ok(
        cli(
            "furnace",
            "zone",
            "HT-04",
            "main",
            "--cubic-feet",
            "40",
            "--low",
            "1000",
            "--high",
            "1800",
        )
    )
    ok(cli("furnace", "wire", "HT-04", "TC-01", "--role", "control"))
    ok(cli("furnace", "wire", "HT-04", "TC-02", "--role", "record"))
    ok(cli("furnace", "qualify", "HT-04", "--low", "1200", "--high", "1700"))


def fit_survey_couple(cli: Callable[..., Result]) -> None:
    ok(cli("sensor", "add", "TC-09", "--type", "N", "--role", "survey"))
    ok(
        cli(
            "sensor",
            "calibrate",
            "TC-09",
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
    )


def run_a_load(cli: Callable[..., Result], tmp_path: Path) -> None:
    ok(
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
            "--weight",
            "1450lb",
            "--part",
            "PN-8891:40:4140",
        )
    )
    ok(cli("load", "charge", "L25-0001", "--at", "2025-06-02T06:00:00"))
    ok(cli("load", "start", "L25-0001", "--at", "2025-06-02T07:00:00"))
    path = tmp_path / "run-2506.csv"
    path.write_text(TRACE)
    ok(cli("load", "attach", "L25-0001", str(path), "--profile", "eurotherm 6100"))
    ok(cli("load", "finish", "L25-0001", "--at", "2025-06-02T12:00:00"))


def test_a_shop_can_be_commissioned_and_run(cli: Callable[..., Result], tmp_path: Path) -> None:
    commission(cli)
    fit_survey_couple(cli)
    run_a_load(cli, tmp_path)

    shown = ok(cli("load", "show", "L25-0001"))
    assert "state         complete" in shown.output
    assert "PN-8891" in shown.output


def test_the_furnace_is_chosen_by_the_analysis_command(cli: Callable[..., Result]) -> None:
    commission(cli)
    result = ok(cli("analyse", "choose", "--at", "1550F", "--band", "25"))
    assert "HT-04" in result.output


def test_the_load_leaves_the_floor_when_it_finishes(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    commission(cli)
    run_a_load(cli, tmp_path)
    assert "nothing on the floor" in ok(cli("load", "floor")).output
    assert "awaiting disposition: 1" in ok(cli("report", "open-work")).output


def test_a_deviation_raises_a_report_that_can_be_closed(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    commission(cli)
    run_a_load(cli, tmp_path)
    raised = ok(
        cli(
            "ncr",
            "raise",
            "--subject",
            "load",
            "--reference",
            "L25-0001",
            "--summary",
            "soak ran nine minutes long",
        )
    )
    assert "NCR-25-001" in raised.output
    ok(cli("ncr", "disposition", "NCR-25-001", "--as", "accept_as_is"))
    ok(cli("ncr", "action", "NCR-25-001", "--note", "concession signed"))
    ok(cli("ncr", "close", "NCR-25-001"))
    assert "(no rows)" in ok(cli("ncr", "list", "--open")).output


def test_the_compliance_report_reflects_the_shop(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    commission(cli)
    fit_survey_couple(cli)
    run_a_load(cli, tmp_path)
    result = ok(cli("report", "compliance"))
    assert "overall     satisfied" in result.output


def test_an_uncalibrated_survey_couple_breaks_compliance(
    cli: Callable[..., Result],
) -> None:
    commission(cli)
    ok(cli("sensor", "add", "TC-09", "--type", "N", "--role", "survey"))
    result = ok(cli("report", "compliance"))
    assert "overall     exception" in result.output
    assert "TC-00009" in result.output


def test_the_database_stays_clean_through_all_of_it(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    commission(cli)
    fit_survey_couple(cli)
    run_a_load(cli, tmp_path)
    assert "database is clean" in ok(cli("db", "check")).output
    counts = ok(cli("db", "counts")).output
    assert "furnace" in counts
    assert "load_record" in counts


def test_the_schema_is_at_the_latest_version(cli: Callable[..., Result]) -> None:
    from quenchline.store.migrations import MIGRATIONS

    result = ok(cli("db", "status"))
    assert f"schema version      {len(MIGRATIONS)}" in result.output
