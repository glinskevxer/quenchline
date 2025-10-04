from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_VALIDATION, main

LAYOUT = """
[layout]
name = "HT-04 main"
time_heading = "Elapsed (min)"
time_unit = "minutes"
scale = "F"

  [[layout.column]]
  heading = "C1"
  sensor = "TC-01"
  location = "front top left"
  corner = true

  [[layout.column]]
  heading = "C2"
  sensor = "TC-02"
  location = "front top right"
  corner = true

  [[layout.column]]
  heading = "C3"
  sensor = "TC-03"
  location = "rear top left"
  corner = true

  [[layout.column]]
  heading = "C4"
  sensor = "TC-04"
  location = "rear top right"
  corner = true

  [[layout.column]]
  heading = "C5"
  sensor = "TC-05"
  location = "centre"
  centre = true
"""


def readings(setpoint: float, spread: float = 4.0) -> str:
    cold = setpoint - 200
    lines = [
        "Elapsed (min),C1,C2,C3,C4,C5",
        f"0,{cold},{cold},{cold},{cold},{cold}",
    ]
    for minute in (10, 20, 40, 70):
        lines.append(
            f"{minute},{setpoint - spread},{setpoint + spread},"
            f"{setpoint - spread},{setpoint + spread},{setpoint}"
        )
    return "\n".join(lines) + "\n"


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-06-10", *args]
        )

    return invoke


@pytest.fixture()
def layout_file(tmp_path: Path) -> Path:
    path = tmp_path / "layout.toml"
    path.write_text(LAYOUT)
    return path


def commission(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    cli(
        "furnace",
        "zone",
        "HT-04",
        "main",
        "--cubic-feet",
        "2",
        "--low",
        "1000",
        "--high",
        "1800",
    )


def test_a_layout_file_prints(cli: Callable[..., Result], layout_file: Path) -> None:
    result = cli("survey", "layout", str(layout_file))
    assert result.exit_code == 0
    assert "survey layout" in result.output
    assert "corners      4" in result.output
    assert "TC-00005 centre" in result.output


def test_a_missing_layout_file_is_refused(cli: Callable[..., Result], tmp_path: Path) -> None:
    result = cli("survey", "layout", str(tmp_path / "nope.toml"))
    assert result.exit_code != 0


def test_a_clean_survey_passes_and_reports_the_range(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    low = tmp_path / "low.csv"
    high = tmp_path / "high.csv"
    low.write_text(readings(1200.0))
    high.write_text(readings(1700.0))
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-004",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1200F={low}",
        "--reading",
        f"1700F={high}",
    )
    assert result.exit_code == 0, result.output
    assert "uniformity survey" in result.output
    assert "positions required for main (2.0 cuft): 5" in result.output
    assert "qualifies HT-04 from 1200 F to 1700 F" in result.output


def test_a_wide_survey_fails(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "wide.csv"
    path.write_text(readings(1550.0, spread=30.0))
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-005",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
    )
    assert result.exit_code == EXIT_VALIDATION
    assert "failed at 1550 F" in result.output


def test_an_unknown_furnace_is_refused(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    path = tmp_path / "run.csv"
    path.write_text(readings(1550.0))
    result = cli(
        "survey",
        "evaluate",
        "HT-99",
        "--number",
        "TUS-25-006",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
    )
    assert result.exit_code == EXIT_NOT_FOUND


def test_an_unknown_zone_is_refused(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "run.csv"
    path.write_text(readings(1550.0))
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-007",
        "--zone",
        "rear",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_a_reading_without_a_path_is_refused(
    cli: Callable[..., Result], layout_file: Path
) -> None:
    commission(cli)
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-008",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        "1550F",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_a_short_soak_fails_the_survey(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "short.csv"
    path.write_text(
        "Elapsed (min),C1,C2,C3,C4,C5\n0,1546,1554,1546,1554,1550\n5,1548,1552,1548,1552,1550\n"
    )
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-009",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
    )
    assert result.exit_code == EXIT_VALIDATION
    assert "short_soak" in result.output


def test_the_soak_floor_can_be_lowered(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "short.csv"
    path.write_text(
        "Elapsed (min),C1,C2,C3,C4,C5\n0,1546,1554,1546,1554,1550\n5,1548,1552,1548,1552,1550\n"
    )
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-010",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
        "--soak",
        "4",
    )
    assert result.exit_code == 0


def test_a_dropout_is_reported(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "dropped.csv"
    lines = readings(1550.0).splitlines()
    lines[-1] = lines[-1].replace("1554.0", "---", 1)
    text = "\n".join(lines) + "\n"
    path.write_text(text)
    result = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-011",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
    )
    assert "survey sensor losses" in result.output
    assert "survey stands  no" in result.output


def test_a_passing_survey_qualifies_the_furnace_and_is_kept(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    low = tmp_path / "low.csv"
    high = tmp_path / "high.csv"
    low.write_text(readings(1200.0))
    high.write_text(readings(1700.0))
    evaluated = cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-020",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1200F={low}",
        "--reading",
        f"1700F={high}",
        "--on",
        "2025-06-01",
    )
    assert evaluated.exit_code == 0, evaluated.output
    shown = cli("furnace", "show", "HT-04")
    assert "1200 F to 1700 F" in shown.output
    board = cli("report", "schedule")
    assert "uniformity_survey" in board.output
    assert "HT-04 main" in board.output


def test_a_failed_survey_is_kept_and_leaves_the_zone_unqualified(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "wide.csv"
    path.write_text(readings(1550.0, spread=30.0))
    cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-25-021",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
        "--on",
        "2025-06-01",
    )
    board = cli("report", "schedule")
    assert "uniformity_survey" in board.output
    compliance = cli("report", "compliance")
    assert "surveys in date" in compliance.output


def test_an_overdue_survey_breaks_compliance(
    cli: Callable[..., Result], layout_file: Path, tmp_path: Path
) -> None:
    commission(cli)
    path = tmp_path / "run.csv"
    path.write_text(readings(1550.0))
    cli(
        "survey",
        "evaluate",
        "HT-04",
        "--number",
        "TUS-24-001",
        "--zone",
        "main",
        "--layout",
        str(layout_file),
        "--reading",
        f"1550F={path}",
        "--on",
        "2023-06-01",
    )
    result = cli("report", "compliance")
    assert "overall     exception" in result.output
    assert "HT-04 main" in result.output
