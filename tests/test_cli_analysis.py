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
            main, ["--database", str(database), "--today", "2025-05-20", *args]
        )

    return invoke


def seed_furnace(
    cli: Callable[..., Result],
    tag: str,
    furnace_class: str = "3",
    cubic_feet: str = "40",
) -> None:
    cli("furnace", "add", tag, "--class", furnace_class, "--instrumentation", "E")
    cli(
        "furnace",
        "zone",
        tag,
        "main",
        "--cubic-feet",
        cubic_feet,
        "--low",
        "1000",
        "--high",
        "1800",
    )
    cli("furnace", "wire", tag, f"TC-{tag[-2:]}", "--role", "control")
    cli("furnace", "qualify", tag, "--low", "1200", "--high", "1700")


def test_choose_lists_the_able_furnaces(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
    seed_furnace(cli, "HT-11", furnace_class="1")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25")
    assert result.exit_code == 0
    assert "furnaces for +25.0 F at 1550 F" in result.output
    rows = [line for line in result.output.splitlines() if line.startswith("HT-")]
    assert rows[0].startswith("HT-04")


def test_choose_hides_the_refusals_by_default(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
    seed_furnace(cli, "HT-06", furnace_class="6")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25")
    assert "HT-06" not in result.output


def test_choose_can_show_the_refusals(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
    seed_furnace(cli, "HT-06", furnace_class="6")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25", "--all")
    assert "HT-06" in result.output
    assert "band_too_wide" in result.output


def test_choose_takes_the_load_volume_into_account(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04", cubic_feet="4")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25", "--cubic-feet", "20")
    assert result.exit_code == EXIT_VALIDATION


def test_choose_reports_the_spare_room(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25", "--cubic-feet", "20")
    assert "20.0" in result.output


def test_choose_with_nothing_qualified(cli: Callable[..., Result]) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "E")
    cli("furnace", "wire", "HT-04", "TC-04", "--role", "control")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25")
    assert result.exit_code == EXIT_VALIDATION


def test_a_band_of_zero_is_refused(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "0")
    assert result.exit_code == EXIT_VALIDATION


def test_workload_of_an_empty_shop(cli: Callable[..., Result]) -> None:
    result = cli("analyse", "workload", "--from", "2025-05-01", "--to", "2025-05-07")
    assert result.exit_code == 0
    assert "loads          0" in result.output
    assert "furnace workload" not in result.output


def test_workload_counts_a_finished_load(cli: Callable[..., Result]) -> None:
    seed_furnace(cli, "HT-04")
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
        "--part",
        "PN-8891:10",
    )
    cli("load", "charge", "L25-0001", "--at", "2025-05-02T06:00:00")
    cli("load", "start", "L25-0001", "--at", "2025-05-02T07:00:00")
    result = cli("analyse", "workload", "--from", "2025-05-01", "--to", "2025-05-07")
    assert "loads          0" in result.output


def test_a_backwards_workload_period_is_refused(cli: Callable[..., Result]) -> None:
    result = cli("analyse", "workload", "--from", "2025-05-07", "--to", "2025-05-01")
    assert result.exit_code == EXIT_VALIDATION


def test_the_workload_header_reports_the_period_length(cli: Callable[..., Result]) -> None:
    result = cli("analyse", "workload", "--from", "2025-05-01", "--to", "2025-05-07")
    assert "period hours   168" in result.output


def test_a_furnace_missing_its_control_sensor_is_refused(
    cli: Callable[..., Result],
) -> None:
    cli("furnace", "add", "HT-09", "--class", "3", "--instrumentation", "E")
    cli(
        "furnace",
        "zone",
        "HT-09",
        "main",
        "--cubic-feet",
        "40",
        "--low",
        "1000",
        "--high",
        "1800",
    )
    cli("furnace", "qualify", "HT-09", "--low", "1200", "--high", "1700")
    result = cli("analyse", "choose", "--at", "1550F", "--band", "25", "--all")
    assert "instrumentation_short" in result.output
