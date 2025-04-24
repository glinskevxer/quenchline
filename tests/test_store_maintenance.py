from __future__ import annotations

from pathlib import Path

import pytest

from quenchline.errors import ValidationError
from quenchline.store.database import Database
from quenchline.store.maintenance import (
    IntegrityReport,
    backup,
    check,
    page_stats,
    restore,
    row_counts,
    size_of,
    vacuum,
)


def test_a_new_database_is_clean() -> None:
    with Database.in_memory() as database:
        report = check(database)
        assert report.is_clean
        assert report.problems == ()
        assert str(report) == "database is clean"


def test_a_report_with_problems_lists_them() -> None:
    report = IntegrityReport(("page 4 is corrupt",), ("work_zone row references missing 0",))
    assert not report.is_clean
    assert len(report.problems) == 2
    assert "2 problem(s)" in str(report)


def test_a_clean_integrity_but_broken_keys_is_not_clean() -> None:
    report = IntegrityReport(("ok",), ("work_zone row references missing 0",))
    assert not report.is_clean


def test_page_stats_come_back() -> None:
    with Database.in_memory() as database:
        stats = page_stats(database)
        assert stats["page_count"] > 0
        assert stats["page_size"] > 0
        assert stats["freelist_count"] >= 0


def test_row_counts_cover_every_table() -> None:
    with Database.in_memory() as database:
        counts = row_counts(database)
        assert "furnace" in counts
        assert counts["furnace"] == 0
        assert counts["schema_migration"] > 0


def test_vacuum_runs(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path) as database:
        vacuum(database)
        assert check(database).is_clean


def test_size_of_a_file(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path).close()
    assert size_of(path) > 0
    with pytest.raises(ValidationError):
        size_of(tmp_path / "nope.sqlite")


def test_a_backup_is_readable(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path) as database:
        database.execute(
            "INSERT INTO furnace (tag, furnace_class, instrumentation, status) "
            "VALUES ('HT-04', 3, 'D', 'in_service')"
        )
        database.connection.commit()
        backup(database, tmp_path / "backup.sqlite")
    with Database.open(tmp_path / "backup.sqlite") as copied:
        assert len(copied.query("SELECT tag FROM furnace")) == 1


def test_a_backup_refuses_to_clobber(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path) as database:
        backup(database, tmp_path / "backup.sqlite")
        with pytest.raises(ValidationError):
            backup(database, tmp_path / "backup.sqlite")


def test_a_backup_creates_its_folder(tmp_path: Path) -> None:
    with Database.open(tmp_path / "shop.sqlite") as database:
        written = backup(database, tmp_path / "nested" / "backup.sqlite")
        assert written.exists()


def test_restore_puts_it_back(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path) as database:
        database.execute(
            "INSERT INTO furnace (tag, furnace_class, instrumentation, status) "
            "VALUES ('HT-04', 3, 'D', 'in_service')"
        )
        database.connection.commit()
        backup(database, tmp_path / "backup.sqlite")
    restore(tmp_path / "backup.sqlite", tmp_path / "restored.sqlite")
    with Database.open(tmp_path / "restored.sqlite") as restored:
        assert len(restored.query("SELECT tag FROM furnace")) == 1


def test_restore_refuses_to_clobber_without_being_told(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path).close()
    with Database.open(path) as database:
        backup(database, tmp_path / "backup.sqlite")
    with pytest.raises(ValidationError):
        restore(tmp_path / "backup.sqlite", path)
    restore(tmp_path / "backup.sqlite", path, overwrite=True)


def test_restoring_something_that_is_not_there(tmp_path: Path) -> None:
    with pytest.raises(ValidationError):
        restore(tmp_path / "nope.sqlite", tmp_path / "shop.sqlite")
