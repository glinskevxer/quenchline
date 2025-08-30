"""An instrument found out of tolerance, and everything that follows from it.

This is the path a shop dreads and the one the package exists for: a controlling
instrument comes back from calibration reading six degrees high, and the
question is not "fix the instrument" but "what did it measure while it was
wrong, and where are those parts now".
"""

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
            main, ["--database", str(database), "--today", "2025-09-01", *args]
        )

    return invoke


def ok(result: Result) -> Result:
    assert result.exit_code == 0, result.output
    return result


def run_a_load(cli: Callable[..., Result], tmp_path: Path, lot: str, day: str) -> None:
    ok(
        cli(
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
            "--part",
            "PN-8891:40",
        )
    )
    ok(cli("load", "charge", lot, "--at", f"{day}T06:00:00"))
    ok(cli("load", "start", lot, "--at", f"{day}T07:00:00"))
    path = tmp_path / f"{lot}.csv"
    tail = 110 + int(lot[-1])
    path.write_text(TRACE + f"{tail},1551,1550,1548,1547\n")
    ok(cli("load", "attach", lot, str(path), "--profile", "eurotherm 6100"))
    ok(cli("load", "finish", lot, "--at", f"{day}T12:00:00"))


def setup_shop(cli: Callable[..., Result], tmp_path: Path) -> None:
    ok(
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
    )
    ok(
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
            "2025-01-10",
        )
    )
    run_a_load(cli, tmp_path, "L25-0001", "2025-03-04")
    run_a_load(cli, tmp_path, "L25-0002", "2025-05-06")
    run_a_load(cli, tmp_path, "L25-0003", "2025-08-20")


def test_an_out_of_tolerance_instrument_names_its_window(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    setup_shop(cli, tmp_path)
    result = ok(
        cli(
            "instrument",
            "calibrate",
            "IC-04",
            "--number",
            "CAL-25-002",
            "--tolerance",
            "2",
            "--point",
            "1550:1556:1550.3",
            "--on",
            "2025-07-01",
        )
    )
    assert "adjusted" in result.output
    assert "work in doubt from 2025-01-10 to 2025-07-01" in result.output


def test_the_window_catches_the_loads_that_ran_inside_it(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    setup_shop(cli, tmp_path)
    ok(
        cli(
            "ncr",
            "raise",
            "--subject",
            "instrument",
            "--reference",
            "IC-04",
            "--summary",
            "found six degrees high at 1550",
        )
    )
    result = ok(
        cli("ncr", "window", "NCR-25-001", "--from", "2025-01-10", "--to", "2025-07-01")
    )
    assert "covers 2 load(s)" in result.output
    assert "L25-0001" in result.output
    assert "L25-0002" in result.output
    assert "L25-0003" not in result.output


def test_the_in_doubt_report_lists_the_same_loads(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    setup_shop(cli, tmp_path)
    cli(
        "ncr",
        "raise",
        "--subject",
        "instrument",
        "--reference",
        "IC-04",
        "--summary",
        "found six degrees high",
    )
    cli("ncr", "window", "NCR-25-001", "--from", "2025-01-10", "--to", "2025-07-01")
    result = ok(cli("ncr", "in-doubt"))
    assert "work in doubt" in result.output
    assert "L25-0001, L25-0002" in result.output


def test_the_report_cannot_close_until_the_window_is_recorded(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    setup_shop(cli, tmp_path)
    cli(
        "ncr",
        "raise",
        "--subject",
        "instrument",
        "--reference",
        "IC-04",
        "--summary",
        "found six degrees high",
    )
    cli("ncr", "disposition", "NCR-25-001", "--as", "review")
    cli("ncr", "action", "NCR-25-001", "--note", "instrument adjusted")
    blocked = cli("ncr", "close", "NCR-25-001")
    assert blocked.exit_code != 0

    ok(cli("ncr", "window", "NCR-25-001", "--from", "2025-01-10", "--to", "2025-07-01"))
    ok(cli("ncr", "close", "NCR-25-001"))
    assert "(no rows)" in ok(cli("ncr", "list", "--open")).output


def test_the_schedule_still_shows_the_instrument_after_all_of_it(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    setup_shop(cli, tmp_path)
    result = ok(cli("report", "schedule"))
    assert "instrument_calibration" in result.output
    assert "IC-04" in result.output
