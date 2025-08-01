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
        return CliRunner().invoke(main, ["--database", str(database), *args])

    return invoke


def judge(cli: Callable[..., Result], *values: str, **flags: str) -> Result:
    args = [
        "hardness",
        "judge",
        "--lot-size",
        flags.get("lot_size", "9"),
        "--scale",
        "HRC",
        "--minimum",
        "40",
        "--maximum",
        "45",
    ]
    for value in values:
        args.extend(["--reading", value])
    if "converted" in flags:
        args.extend(["--converted", flags["converted"]])
    if flags.get("retest"):
        args.append("--retest")
    if flags.get("allow_converted"):
        args.append("--allow-converted")
    if "max_spread" in flags:
        args.extend(["--max-spread", flags["max_spread"]])
    return cli(*args)


def test_conversion_between_scales(cli: Callable[..., Result]) -> None:
    result = cli("hardness", "convert", "45HRC", "--to", "HV")
    assert result.exit_code == 0
    assert "45.0 HRC is about 446.0 HV" in result.output


def test_conversion_outside_the_overlap_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("hardness", "convert", "60HRB", "--to", "HRC")
    assert result.exit_code == EXIT_VALIDATION


def test_a_superficial_reading_does_not_convert(cli: Callable[..., Result]) -> None:
    result = cli("hardness", "convert", "90HR15N", "--to", "HRC")
    assert result.exit_code == EXIT_VALIDATION


def test_an_unparsable_reading_is_refused(cli: Callable[..., Result]) -> None:
    assert cli("hardness", "convert", "45", "--to", "HV").exit_code == EXIT_VALIDATION


def test_the_sample_size_is_reported(cli: Callable[..., Result]) -> None:
    result = cli("hardness", "sample", "--lot-size", "100")
    assert "first sample   10" in result.output
    assert "retest sample  20" in result.output


def test_a_lot_of_nothing_is_refused(cli: Callable[..., Result]) -> None:
    assert cli("hardness", "sample", "--lot-size", "0").exit_code == EXIT_VALIDATION


def test_a_clean_lot_is_accepted(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", "43")
    assert result.exit_code == 0
    assert "verdict          accepted" in result.output
    assert "average          42.0" in result.output


def test_one_bad_reading_buys_a_retest(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", "38")
    assert result.exit_code == EXIT_VALIDATION
    assert "retest" in result.output


def test_two_bad_readings_reject(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "38", "37")
    assert "verdict          rejected" in result.output


def test_a_clean_retest_is_accepted(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", "43", "41.5", "42.5", "43.5", retest="yes")
    assert result.exit_code == 0
    assert "required sample  6" in result.output


def test_too_few_readings_is_a_rejection(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", lot_size="100")
    assert "required sample" in result.output
    assert result.exit_code == EXIT_VALIDATION


def test_converted_readings_are_refused_by_default(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", converted="43")
    assert "converted readings cannot be used" in result.output


def test_converted_readings_can_be_allowed(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", converted="43", allow_converted="yes")
    assert result.exit_code == 0
    assert "converted" in result.output


def test_a_spread_limit_can_reject_readings_in_range(cli: Callable[..., Result]) -> None:
    result = judge(cli, "40.5", "42", "44.5", max_spread="2")
    assert "spread of 4" in result.output


def test_the_table_marks_the_out_of_range_reading(cli: Callable[..., Result]) -> None:
    result = judge(cli, "41", "42", "38")
    assert "measured  out" in result.output


def test_a_junk_reading_is_refused(cli: Callable[..., Result]) -> None:
    result = judge(cli, "hard")
    assert result.exit_code != 0


def test_a_specification_with_no_limit_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "hardness",
        "judge",
        "--lot-size",
        "9",
        "--scale",
        "HRC",
        "--reading",
        "41",
    )
    assert result.exit_code == EXIT_VALIDATION
