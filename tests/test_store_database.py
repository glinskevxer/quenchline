from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from quenchline.errors import StateError, ValidationError
from quenchline.store.database import (
    SCHEMA_TABLE,
    ChecksumMismatch,
    Database,
    require_table,
)
from quenchline.store.migrations import MIGRATIONS, Migration

SMALL = (
    Migration(1, "one", ("CREATE TABLE alpha (id INTEGER PRIMARY KEY)",)),
    Migration(2, "two", ("CREATE TABLE beta (id INTEGER PRIMARY KEY)",)),
)


def test_a_new_database_runs_every_migration() -> None:
    with Database.in_memory() as database:
        assert database.version == len(MIGRATIONS)
        assert len(database.applied()) == len(MIGRATIONS)


def test_the_shipped_tables_are_created() -> None:
    with Database.in_memory() as database:
        tables = database.tables()
        for name in ("furnace", "work_zone", "thermocouple", "load_record", "nonconformance"):
            assert name in tables
        assert SCHEMA_TABLE in tables


def test_foreign_keys_are_turned_on() -> None:
    with Database.in_memory() as database:
        assert database.foreign_keys_on()


def test_a_foreign_key_is_actually_enforced() -> None:
    with Database.in_memory() as database, pytest.raises(sqlite3.IntegrityError):
        database.execute(
            "INSERT INTO work_zone (furnace_tag, name, cubic_feet, low_f, high_f) "
            "VALUES ('HT-99', 'main', 40, 1000, 1800)"
        )


def test_migrating_twice_runs_nothing_the_second_time() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        assert database.version == 2
        assert database.migrate(SMALL) == []


def test_a_partly_migrated_database_catches_up(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL[:1]).close()
    with Database.open(path, migrations=SMALL) as database:
        assert database.version == 2
        assert "beta" in database.tables()


def test_migrate_reports_what_it_ran(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path, migrations=SMALL[:1], migrate=False) as database:
        ran = database.migrate(SMALL)
        assert [m.version for m in ran] == [1, 2]


def test_an_edited_migration_stops_the_database_opening(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL).close()
    edited = (
        Migration(1, "one", ("CREATE TABLE alpha (id TEXT PRIMARY KEY)",)),
        SMALL[1],
    )
    with pytest.raises(ChecksumMismatch) as caught:
        Database.open(path, migrations=edited)
    assert caught.value.version == 1
    assert caught.value.expected != caught.value.found


def test_a_checksum_mismatch_is_a_state_error(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL).close()
    edited = (Migration(1, "one", ("CREATE TABLE alpha (id TEXT)",)), SMALL[1])
    with pytest.raises(StateError):
        Database.open(path, migrations=edited)


def test_reindenting_a_migration_does_not_trip_the_guard(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL).close()
    reindented = (
        Migration(1, "one", ("  CREATE   TABLE alpha\n  (id INTEGER PRIMARY KEY)  ",)),
        SMALL[1],
    )
    with Database.open(path, migrations=reindented) as database:
        assert database.version == 2


def test_a_database_ahead_of_the_code_is_refused(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL).close()
    with pytest.raises(StateError):
        Database.open(path, migrations=SMALL[:1])


def test_opening_without_migrating_leaves_the_schema_alone(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path, migrations=SMALL, migrate=False) as database:
        assert database.version == 0
        assert "alpha" not in database.tables()


def test_a_broken_migration_list_is_refused() -> None:
    broken = (Migration(2, "two", ("SELECT 1",)),)
    with pytest.raises(ValidationError):
        Database.in_memory(migrations=broken)


def test_a_transaction_rolls_back_on_failure() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        with pytest.raises(RuntimeError), database.transaction() as connection:
            connection.execute("INSERT INTO alpha (id) VALUES (1)")
            raise RuntimeError("something went wrong")
        assert database.query("SELECT id FROM alpha") == []


def test_a_transaction_commits_on_success() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        with database.transaction() as connection:
            connection.execute("INSERT INTO alpha (id) VALUES (1)")
        assert len(database.query("SELECT id FROM alpha")) == 1


def test_query_helpers() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        database.execute("INSERT INTO alpha (id) VALUES (7)")
        row = database.one("SELECT id FROM alpha WHERE id = ?", (7,))
        assert row is not None
        assert row["id"] == 7
        assert database.one("SELECT id FROM alpha WHERE id = ?", (9,)) is None


def test_applied_rows_carry_the_name_and_time() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        rows = database.applied()
        assert [r.name for r in rows] == ["one", "two"]
        assert all(r.applied_at for r in rows)


def test_require_table() -> None:
    with Database.in_memory(migrations=SMALL) as database:
        require_table(database, "alpha")
        with pytest.raises(ValidationError):
            require_table(database, "gamma")


def test_a_new_database_has_nothing_pending() -> None:
    with Database.in_memory() as database:
        assert database.pending() == []
        assert database.is_current()


def test_pending_lists_what_has_not_run(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    Database.open(path, migrations=SMALL[:1]).close()
    with Database.open(path, migrations=SMALL[:1], migrate=False) as database:
        waiting = database.pending(SMALL)
        assert [m.version for m in waiting] == [2]
        assert not database.is_current(SMALL)


def test_pending_is_in_the_order_they_will_run(tmp_path: Path) -> None:
    path = tmp_path / "shop.sqlite"
    with Database.open(path, migrations=SMALL, migrate=False) as database:
        assert [m.version for m in database.pending(SMALL)] == [1, 2]
