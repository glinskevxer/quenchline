from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_NOT_FOUND, EXIT_VALIDATION, main

GOOD = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,100,101,95,96
30,1545,1546,1538,1539
60,1552,1551,1549,1548
"""

DIRTY = """Elapsed (min),Channel 1,Channel 2,Channel 3,Channel 4
0,100,101,95,96
soon,1545,1546,1538,1539
later,1552,1551,1549,1548
"""

EXTRA_PROFILE = """
[[profile]]
name = "yokogawa mv1000"
time_heading = "Elapsed"
time_unit = "seconds"
scale = "C"

  [[profile.column]]
  heading = "CH01"
  key = "C1"
  role = "control"
"""


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-04-01", *args]
        )

    return invoke


def test_the_built_in_profiles_are_listed(cli: Callable[..., Result]) -> None:
    result = cli("ingest", "profiles")
    assert result.exit_code == 0
    assert "mapping profiles" in result.output
    assert "eurotherm 6100" in result.output
    assert "datapaq tp3" in result.output


def test_a_semicolon_profile_shows_its_delimiter(cli: Callable[..., Result]) -> None:
    assert ";" in cli("ingest", "profiles").output


def test_extra_profiles_load_from_a_file(cli: Callable[..., Result], tmp_path: Path) -> None:
    path = tmp_path / "profiles.toml"
    path.write_text(EXTRA_PROFILE)
    result = cli("ingest", "profiles", "--file", str(path))
    assert "yokogawa mv1000" in result.output


def test_checking_a_clean_file(cli: Callable[..., Result], tmp_path: Path) -> None:
    path = tmp_path / "run.csv"
    path.write_text(GOOD)
    result = cli("ingest", "check", str(path), "--profile", "eurotherm 6100")
    assert result.exit_code == 0
    assert "run.csv: imported" in result.output
    assert "rows seen  3" in result.output
    assert "channels" in result.output


def test_checking_reports_the_bad_rows(cli: Callable[..., Result], tmp_path: Path) -> None:
    path = tmp_path / "dirty.csv"
    path.write_text(DIRTY)
    result = cli("ingest", "check", str(path), "--profile", "eurotherm 6100")
    assert "bad_time   2" in result.output


def test_checking_with_an_unknown_profile(cli: Callable[..., Result], tmp_path: Path) -> None:
    path = tmp_path / "run.csv"
    path.write_text(GOOD)
    result = cli("ingest", "check", str(path), "--profile", "nothing")
    assert result.exit_code == EXIT_NOT_FOUND


def test_running_a_folder(cli: Callable[..., Result], tmp_path: Path) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    (folder / "a.csv").write_text(GOOD)
    (folder / "b.csv").write_text(GOOD.replace("1552", "1553"))
    result = cli("ingest", "run", str(folder), "--profile", "eurotherm 6100")
    assert result.exit_code == 0
    assert "2 imported, 0 rejected" in result.output


def test_a_duplicate_file_is_rejected(cli: Callable[..., Result], tmp_path: Path) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    (folder / "a.csv").write_text(GOOD)
    (folder / "b.csv").write_text(GOOD)
    result = cli("ingest", "run", str(folder), "--profile", "eurotherm 6100")
    assert "duplicate" in result.output
    assert "1 imported, 1 rejected" in result.output


def test_a_dirty_file_is_rejected_by_the_tolerance(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    (folder / "a.csv").write_text(DIRTY)
    result = cli("ingest", "run", str(folder), "--profile", "eurotherm 6100")
    assert "too_many_bad_rows" in result.output


def test_a_generous_tolerance_takes_it(cli: Callable[..., Result], tmp_path: Path) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    (folder / "a.csv").write_text(DIRTY)
    result = cli(
        "ingest", "run", str(folder), "--profile", "eurotherm 6100", "--tolerance", "0.9"
    )
    assert "1 imported, 0 rejected" in result.output


def test_a_tolerance_outside_a_fraction_is_refused(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    result = cli(
        "ingest", "run", str(folder), "--profile", "eurotherm 6100", "--tolerance", "5"
    )
    assert result.exit_code == EXIT_VALIDATION


def test_a_pattern_can_be_given(cli: Callable[..., Result], tmp_path: Path) -> None:
    folder = tmp_path / "traces"
    folder.mkdir()
    (folder / "a.dat").write_text(GOOD)
    result = cli(
        "ingest", "run", str(folder), "--profile", "eurotherm 6100", "--pattern", "*.dat"
    )
    assert "1 imported" in result.output
