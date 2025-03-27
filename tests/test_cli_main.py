from __future__ import annotations

from datetime import date
from pathlib import Path

import pytest
from click.testing import CliRunner

from quenchline.cli.context import Context, parse_day
from quenchline.cli.main import (
    EXIT_CONFLICT,
    EXIT_NOT_FOUND,
    EXIT_STATE,
    EXIT_VALIDATION,
    exit_code_for,
    main,
    run,
)
from quenchline.errors import (
    ConflictError,
    NotFoundError,
    QuenchlineError,
    StateError,
    ValidationError,
)
from quenchline.temperature import Scale


def test_parse_day_falls_back() -> None:
    fallback = date(2025, 4, 1)
    assert parse_day(None, fallback) == fallback
    assert parse_day(" 2025-01-08 ", fallback) == date(2025, 1, 8)


def test_parse_day_refuses_junk() -> None:
    with pytest.raises(ValidationError):
        parse_day("yesterday", date(2025, 4, 1))


def test_a_context_resolves_defaults() -> None:
    context = Context.build(environ={}, today=date(2025, 4, 1))
    assert context.today == date(2025, 4, 1)
    assert context.database_path == Path("quenchline.sqlite")
    assert not context.is_open


def test_the_database_option_beats_the_settings(tmp_path: Path) -> None:
    context = Context.build(database=tmp_path / "other.sqlite", environ={})
    assert context.database_path.name == "other.sqlite"


def test_the_shop_opens_once(tmp_path: Path) -> None:
    with Context.build(database=tmp_path / "shop.sqlite", environ={}) as context:
        first = context.shop()
        assert context.shop() is first
        assert context.is_open
    assert not context.is_open


def test_settings_are_loaded_from_a_file(tmp_path: Path) -> None:
    path = tmp_path / "quenchline.toml"
    path.write_text('[quenchline]\nreport_scale = "C"\nshop_name = "Night Shift"\n')
    context = Context.build(settings_path=path, environ={})
    assert context.settings.report_scale is Scale.CELSIUS
    assert context.settings.shop_name == "Night Shift"


def test_exit_codes_map_to_error_types() -> None:
    assert exit_code_for(NotFoundError("furnace", "HT-99")) == EXIT_NOT_FOUND
    assert exit_code_for(ConflictError("furnace", "HT-04")) == EXIT_CONFLICT
    assert exit_code_for(StateError("no")) == EXIT_STATE
    assert exit_code_for(ValidationError("no")) == EXIT_VALIDATION
    assert exit_code_for(QuenchlineError("no")) == 1


def test_the_version_is_printed() -> None:
    result = CliRunner().invoke(main, ["--version"])
    assert result.exit_code == 0
    assert "quenchline" in result.output


def test_the_help_lists_the_commands() -> None:
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "settings" in result.output


def test_settings_command_prints_the_resolved_values(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main,
        ["--database", str(tmp_path / "shop.sqlite"), "--today", "2025-04-01", "settings"],
    )
    assert result.exit_code == 0
    assert "today" in result.output
    assert "2025-04-01" in result.output
    assert "shop.sqlite" in result.output


def test_a_bad_date_is_reported_as_one_line(tmp_path: Path) -> None:
    code = run(
        [
            "--database",
            str(tmp_path / "shop.sqlite"),
            "--today",
            "yesterday",
            "settings",
        ]
    )
    assert code == EXIT_VALIDATION


def test_a_good_run_exits_zero(tmp_path: Path) -> None:
    assert run(["--database", str(tmp_path / "shop.sqlite"), "settings"]) == 0


def test_an_unknown_command_is_a_click_error(tmp_path: Path) -> None:
    code = run(["--database", str(tmp_path / "shop.sqlite"), "nonsense"])
    assert code != 0


def test_the_settings_command_shows_the_database_actually_in_use(tmp_path: Path) -> None:
    result = CliRunner().invoke(
        main, ["--database", str(tmp_path / "other.sqlite"), "settings"]
    )
    assert "database in use" in result.output
    assert "other.sqlite" in result.output
