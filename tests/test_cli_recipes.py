from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import EXIT_CONFLICT, EXIT_NOT_FOUND, EXIT_STATE, EXIT_VALIDATION, main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(
            main, ["--database", str(database), "--today", "2025-06-25", *args]
        )

    return invoke


def add(cli: Callable[..., Result], revision: str = "C") -> Result:
    return cli(
        "recipe",
        "add",
        "HT-4140-Q",
        "--revision",
        revision,
        "--title",
        "4140 harden and temper",
        "--material",
        "4140",
        "--load-sensors",
        "2",
        "--step",
        "ramp:heat:setpoint=1550F,max_rate=400",
        "--step",
        "soak:austenitise:setpoint=1550F,band=25,minimum=1h",
        "--step",
        "quench:oil quench:delay=30s,medium=AAA fast oil",
        "--step",
        "temper:temper:setpoint=400F,band=15,minimum=2h",
    )


def test_a_recipe_can_be_written(cli: Callable[..., Result]) -> None:
    result = add(cli)
    assert result.exit_code == 0
    assert "added HT-4140-Q rev C as a draft with 4 step(s)" in result.output


def test_the_same_revision_cannot_be_written_twice(cli: Callable[..., Result]) -> None:
    add(cli)
    assert add(cli).exit_code == EXIT_CONFLICT


def test_a_step_of_the_wrong_shape_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "recipe",
        "add",
        "HT-1",
        "--revision",
        "A",
        "--title",
        "x",
        "--step",
        "soak",
    )
    assert result.exit_code != 0


def test_an_unknown_step_kind_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "recipe",
        "add",
        "HT-1",
        "--revision",
        "A",
        "--title",
        "x",
        "--step",
        "bake:something:setpoint=1550F",
    )
    assert result.exit_code != 0


def test_a_malformed_option_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "recipe",
        "add",
        "HT-1",
        "--revision",
        "A",
        "--title",
        "x",
        "--step",
        "hold:wait:minimum",
    )
    assert result.exit_code != 0


def test_a_temper_before_a_quench_is_refused(cli: Callable[..., Result]) -> None:
    result = cli(
        "recipe",
        "add",
        "HT-1",
        "--revision",
        "A",
        "--title",
        "backwards",
        "--step",
        "soak:austenitise:setpoint=1550F,band=25,minimum=1h",
        "--step",
        "temper:temper:setpoint=400F,band=15,minimum=2h",
    )
    assert result.exit_code == EXIT_VALIDATION


def test_nothing_is_runnable_until_a_release(cli: Callable[..., Result]) -> None:
    add(cli)
    assert "nothing is released" in cli("recipe", "runnable").output
    assert cli("recipe", "show", "HT-4140-Q").exit_code == EXIT_VALIDATION


def test_releasing_makes_it_runnable(cli: Callable[..., Result]) -> None:
    add(cli)
    released = cli("recipe", "release", "HT-4140-Q", "--revision", "C")
    assert "rev C released" in released.output
    assert "HT-4140-Q rev C" in cli("recipe", "runnable").output


def test_releasing_a_second_revision_supersedes_the_first(
    cli: Callable[..., Result],
) -> None:
    add(cli, "C")
    add(cli, "D")
    cli("recipe", "release", "HT-4140-Q", "--revision", "C", "--on", "2025-03-01")
    result = cli("recipe", "release", "HT-4140-Q", "--revision", "D", "--on", "2025-06-01")
    assert "rev C superseded" in result.output
    listed = cli("recipe", "list").output
    assert "superseded" in listed
    assert "released" in listed


def test_a_superseded_revision_cannot_come_back(cli: Callable[..., Result]) -> None:
    add(cli, "C")
    add(cli, "D")
    cli("recipe", "release", "HT-4140-Q", "--revision", "C", "--on", "2025-03-01")
    cli("recipe", "release", "HT-4140-Q", "--revision", "D", "--on", "2025-06-01")
    again = cli("recipe", "release", "HT-4140-Q", "--revision", "C", "--on", "2025-06-02")
    assert again.exit_code == EXIT_STATE


def test_withdrawing_takes_it_out_of_use(cli: Callable[..., Result]) -> None:
    add(cli)
    cli("recipe", "release", "HT-4140-Q", "--revision", "C")
    assert "withdrawn" in cli("recipe", "withdraw", "HT-4140-Q", "--revision", "C").output
    assert "nothing is released" in cli("recipe", "runnable").output


def test_show_prints_the_cycle(cli: Callable[..., Result]) -> None:
    add(cli)
    result = cli("recipe", "show", "HT-4140-Q", "--revision", "C")
    assert "recipe             HT-4140-Q rev C" in result.output
    assert "graded soaks       2" in result.output
    assert "minimum soak time  3:00" in result.output
    assert "has a quench       yes" in result.output
    assert "AAA fast oil" in result.output


def test_show_defaults_to_the_released_revision(cli: Callable[..., Result]) -> None:
    add(cli, "C")
    add(cli, "D")
    cli("recipe", "release", "HT-4140-Q", "--revision", "D")
    result = cli("recipe", "show", "HT-4140-Q")
    assert "HT-4140-Q rev D" in result.output


def test_show_of_an_unknown_revision(cli: Callable[..., Result]) -> None:
    add(cli)
    assert cli("recipe", "show", "HT-4140-Q", "--revision", "Z").exit_code == EXIT_NOT_FOUND


def test_listing_can_be_filtered_by_code(cli: Callable[..., Result]) -> None:
    add(cli)
    cli(
        "recipe",
        "add",
        "HT-8620-C",
        "--revision",
        "A",
        "--title",
        "carburise",
        "--step",
        "soak:carburise:setpoint=1700F,band=25,minimum=4h",
    )
    everything = cli("recipe", "list").output
    assert "HT-4140-Q" in everything
    assert "HT-8620-C" in everything
    one = cli("recipe", "list", "--code", "HT-8620-C").output
    assert "HT-4140-Q" not in one
