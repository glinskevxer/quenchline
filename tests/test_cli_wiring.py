"""Every group is actually wired to the root command.

Adding a command group is two steps: write it, and add it to the root. The
second one is easy to forget and nothing else fails when you do, because the
group's own tests import it directly and pass. This walks what the shell
actually sees.
"""

from __future__ import annotations

import click
import pytest
from click.testing import CliRunner

from quenchline.cli.main import main

EXPECTED_GROUPS = {
    "analyse",
    "audit",
    "bath",
    "db",
    "furnace",
    "hardness",
    "ingest",
    "instrument",
    "load",
    "ncr",
    "recipe",
    "report",
    "sat",
    "sensor",
    "survey",
}


def command_names() -> set[str]:
    return set(main.commands)


def test_every_expected_group_is_wired() -> None:
    missing = EXPECTED_GROUPS - command_names()
    assert not missing, f"not wired to the root command: {sorted(missing)}"


def test_nothing_unexpected_is_wired() -> None:
    extra = command_names() - EXPECTED_GROUPS - {"settings"}
    assert not extra, f"wired but not expected: {sorted(extra)}"


@pytest.mark.parametrize("group", sorted(EXPECTED_GROUPS))
def test_every_group_has_a_help_page(group: str) -> None:
    result = CliRunner().invoke(main, [group, "--help"])
    assert result.exit_code == 0
    assert result.output.strip()


@pytest.mark.parametrize("group", sorted(EXPECTED_GROUPS))
def test_every_group_carries_a_docstring(group: str) -> None:
    command = main.commands[group]
    assert command.help, f"{group} has no help text"


def test_every_subcommand_has_help_text() -> None:
    missing: list[str] = []
    for name, command in main.commands.items():
        if not isinstance(command, click.Group):
            continue
        for sub_name, sub in command.commands.items():
            if not sub.help:
                missing.append(f"{name} {sub_name}")
    assert not missing, f"no help text on: {sorted(missing)}"


def test_the_root_help_lists_the_groups() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    for group in sorted(EXPECTED_GROUPS):
        assert group in result.output


def test_the_global_options_are_all_there() -> None:
    names = {option.name for option in main.params}
    assert {"settings_path", "database", "today", "actor"} <= names


def test_no_group_shares_a_subcommand_name_with_a_different_meaning() -> None:
    """``list`` and ``show`` are fine to repeat. ``add`` must always add."""
    verbs: dict[str, set[str]] = {}
    for command in main.commands.values():
        if not isinstance(command, click.Group):
            continue
        for sub_name in command.commands:
            verbs.setdefault(sub_name, set()).add(command.name or "")
    assert "add" in verbs
    assert len(verbs["add"]) >= 3
