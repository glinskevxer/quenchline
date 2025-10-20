from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest
from click.testing import CliRunner, Result

from quenchline.cli.main import main


@pytest.fixture()
def cli(tmp_path: Path) -> Callable[..., Result]:
    database = tmp_path / "shop.sqlite"

    def invoke(*args: str) -> Result:
        return CliRunner().invoke(main, ["--database", str(database), *args])

    return invoke


def test_status_reports_the_schema_version(cli: Callable[..., Result]) -> None:
    result = cli("db", "status")
    assert result.exit_code == 0
    assert "schema version" in result.output
    assert "pages" in result.output


def test_migrations_are_listed(cli: Callable[..., Result]) -> None:
    result = cli("db", "migrations")
    assert "applied migrations" in result.output
    assert "furnaces and zones" in result.output


def test_counts_list_every_table(cli: Callable[..., Result]) -> None:
    result = cli("db", "counts")
    assert "row counts" in result.output
    assert "furnace" in result.output


def test_the_check_passes_on_a_new_database(cli: Callable[..., Result]) -> None:
    result = cli("db", "check")
    assert result.exit_code == 0
    assert "database is clean" in result.output


def test_vacuum_reports_the_page_change(cli: Callable[..., Result]) -> None:
    result = cli("db", "vacuum")
    assert result.exit_code == 0
    assert "pages" in result.output


def test_backup_and_restore(cli: Callable[..., Result], tmp_path: Path) -> None:
    cli("furnace", "add", "HT-04", "--class", "3", "--instrumentation", "D")
    destination = tmp_path / "backup.sqlite"
    taken = cli("db", "backup", str(destination))
    assert taken.exit_code == 0
    assert destination.exists()

    restored = cli("db", "restore", str(destination), "--overwrite")
    assert restored.exit_code == 0
    assert "HT-04" in cli("furnace", "list").output


def test_restore_without_overwrite_is_refused(
    cli: Callable[..., Result], tmp_path: Path
) -> None:
    destination = tmp_path / "backup.sqlite"
    cli("db", "backup", str(destination))
    result = cli("db", "restore", str(destination))
    assert result.exit_code != 0


def test_a_current_database_has_nothing_pending(cli: Callable[..., Result]) -> None:
    result = cli("db", "pending")
    assert result.exit_code == 0
    assert "schema is current at version" in result.output


def test_the_version_command_agrees_with_the_database(cli: Callable[..., Result]) -> None:
    version = cli("version").output
    status = cli("db", "status").output
    assert "up to date              yes" in version
    assert "schema version" in status
