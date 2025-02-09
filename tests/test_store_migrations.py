from __future__ import annotations

import pytest

from quenchline.errors import ValidationError
from quenchline.store.migrations import (
    MIGRATIONS,
    Migration,
    checksum_of,
    find,
    latest_version,
    validate,
)


def test_the_shipped_migrations_are_a_contiguous_run() -> None:
    validate()
    assert latest_version() == len(MIGRATIONS)
    assert [m.version for m in MIGRATIONS] == list(range(1, len(MIGRATIONS) + 1))


def test_every_shipped_migration_has_a_checksum() -> None:
    checksums = {m.checksum for m in MIGRATIONS}
    assert len(checksums) == len(MIGRATIONS)
    assert all(len(c) == 32 for c in checksums)


def test_migration_validation() -> None:
    with pytest.raises(ValidationError):
        Migration(0, "bad", ("SELECT 1",))
    with pytest.raises(ValidationError):
        Migration(1, "  ", ("SELECT 1",))
    with pytest.raises(ValidationError):
        Migration(1, "bad", ())


def test_migration_text() -> None:
    assert str(Migration(3, "sensor usage", ("SELECT 1",))) == "003 sensor usage"


def test_a_checksum_ignores_reindentation() -> None:
    tight = ("CREATE TABLE a (id INTEGER)",)
    loose = ("  CREATE TABLE a\n      (id INTEGER)  ",)
    assert checksum_of(tight) == checksum_of(loose)


def test_a_checksum_notices_a_real_change() -> None:
    assert checksum_of(("CREATE TABLE a (id INTEGER)",)) != checksum_of(
        ("CREATE TABLE a (id TEXT)",)
    )


def test_a_checksum_notices_a_reordering() -> None:
    assert checksum_of(("A", "B")) != checksum_of(("B", "A"))


def test_validate_catches_a_gap() -> None:
    migrations = (
        Migration(1, "one", ("SELECT 1",)),
        Migration(3, "three", ("SELECT 3",)),
    )
    with pytest.raises(ValidationError):
        validate(migrations)


def test_validate_catches_a_duplicate_version() -> None:
    migrations = (
        Migration(1, "one", ("SELECT 1",)),
        Migration(1, "also one", ("SELECT 2",)),
    )
    with pytest.raises(ValidationError):
        validate(migrations)


def test_validate_catches_a_duplicate_name() -> None:
    migrations = (
        Migration(1, "one", ("SELECT 1",)),
        Migration(2, "one", ("SELECT 2",)),
    )
    with pytest.raises(ValidationError):
        validate(migrations)


def test_validate_catches_an_out_of_order_list() -> None:
    migrations = (
        Migration(2, "two", ("SELECT 2",)),
        Migration(1, "one", ("SELECT 1",)),
    )
    with pytest.raises(ValidationError):
        validate(migrations)


def test_validate_refuses_an_empty_list() -> None:
    with pytest.raises(ValidationError):
        validate(())


def test_find_returns_the_named_migration() -> None:
    assert find(1).name == "furnaces and zones"
    with pytest.raises(ValidationError):
        find(999)


def test_the_first_migration_creates_the_furnace_table() -> None:
    statements = " ".join(find(1).statements)
    assert "CREATE TABLE furnace" in statements
    assert "CREATE TABLE work_zone" in statements


def test_the_load_migration_indexes_by_furnace() -> None:
    statements = " ".join(find(4).statements)
    assert "CREATE INDEX load_by_furnace" in statements
