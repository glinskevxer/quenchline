"""Opening the database and keeping its schema honest.

Opening is not a passive act here. It applies any migrations the file has not
seen, and before it does that it checks every migration the file *has* seen
against the code's own checksum for it. A mismatch stops the program.

The alternative, which plenty of shops live with, is a database whose schema
nobody can describe: applied in some order, edited by hand once in 2019, and
now subtly different from every other install. The check costs a few
milliseconds at startup and removes that entire class of problem.

Foreign keys are turned on explicitly. SQLite has them off by default, and a
schema full of ``REFERENCES`` clauses that are not enforced is worse than one
without them, because it looks safe.
"""

from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from ..errors import StateError, ValidationError
from .migrations import MIGRATIONS, Migration, validate

SCHEMA_TABLE = "schema_migration"

_SCHEMA_TABLE_SQL = f"""
CREATE TABLE IF NOT EXISTS {SCHEMA_TABLE} (
    version INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    checksum TEXT NOT NULL,
    applied_at TEXT NOT NULL
)
"""


@dataclass(frozen=True)
class AppliedMigration:
    """One row of the migration table."""

    version: int
    name: str
    checksum: str
    applied_at: str


class ChecksumMismatch(StateError):
    """A migration was edited after it had already been applied."""

    def __init__(self, version: int, expected: str, found: str) -> None:
        super().__init__(
            f"migration {version} was applied with checksum {found} "
            f"but the code now says {expected}",
            state="schema_drift",
        )
        self.version = version
        self.expected = expected
        self.found = found


class Database:
    """A connection to one shop database."""

    def __init__(self, connection: sqlite3.Connection) -> None:
        self.connection = connection
        self.connection.row_factory = sqlite3.Row
        self.connection.execute("PRAGMA foreign_keys = ON")

    @classmethod
    def open(
        cls,
        path: Path | str,
        *,
        migrations: tuple[Migration, ...] = MIGRATIONS,
        migrate: bool = True,
    ) -> Database:
        """Open, or create, a database file and bring its schema up to date."""
        validate(migrations)
        connection = sqlite3.connect(str(path))
        database = cls(connection)
        database.ensure_schema_table()
        database.verify(migrations)
        if migrate:
            database.migrate(migrations)
        return database

    @classmethod
    def in_memory(cls, *, migrations: tuple[Migration, ...] = MIGRATIONS) -> Database:
        return cls.open(":memory:", migrations=migrations)

    def close(self) -> None:
        self.connection.close()

    def ensure_schema_table(self) -> None:
        self.connection.execute(_SCHEMA_TABLE_SQL)
        self.connection.commit()

    def applied(self) -> list[AppliedMigration]:
        rows = self.connection.execute(
            f"SELECT version, name, checksum, applied_at FROM {SCHEMA_TABLE} ORDER BY version"
        ).fetchall()
        return [
            AppliedMigration(row["version"], row["name"], row["checksum"], row["applied_at"])
            for row in rows
        ]

    @property
    def version(self) -> int:
        rows = self.applied()
        return rows[-1].version if rows else 0

    def verify(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> None:
        """Check every applied migration still matches the code."""
        by_version = {m.version: m for m in migrations}
        for row in self.applied():
            migration = by_version.get(row.version)
            if migration is None:
                raise StateError(
                    f"the database has migration {row.version} and the code does not",
                    state="unknown_migration",
                )
            if migration.checksum != row.checksum:
                raise ChecksumMismatch(row.version, migration.checksum, row.checksum)

    def pending(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[Migration]:
        """Migrations this file has not seen yet, in the order they will run."""
        done = {row.version for row in self.applied()}
        return [m for m in migrations if m.version not in done]

    def is_current(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> bool:
        return not self.pending(migrations)

    def migrate(self, migrations: tuple[Migration, ...] = MIGRATIONS) -> list[Migration]:
        """Apply everything the database has not seen. Returns what it ran."""
        done = {row.version for row in self.applied()}
        ran: list[Migration] = []
        for migration in migrations:
            if migration.version in done:
                continue
            with self.transaction():
                for statement in migration.statements:
                    self.connection.execute(statement)
                self.connection.execute(
                    f"INSERT INTO {SCHEMA_TABLE} (version, name, checksum, applied_at) "
                    "VALUES (?, ?, ?, ?)",
                    (
                        migration.version,
                        migration.name,
                        migration.checksum,
                        datetime.now(UTC).isoformat(timespec="seconds"),
                    ),
                )
            ran.append(migration)
        return ran

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        """A unit of work that rolls back on any exception."""
        try:
            yield self.connection
        except Exception:
            self.connection.rollback()
            raise
        self.connection.commit()

    def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Cursor:
        return self.connection.execute(sql, parameters)

    def query(self, sql: str, parameters: tuple[object, ...] = ()) -> list[sqlite3.Row]:
        return self.connection.execute(sql, parameters).fetchall()

    def one(self, sql: str, parameters: tuple[object, ...] = ()) -> sqlite3.Row | None:
        row: sqlite3.Row | None = self.connection.execute(sql, parameters).fetchone()
        return row

    def tables(self) -> list[str]:
        rows = self.query("SELECT name FROM sqlite_master WHERE type = 'table' ORDER BY name")
        return [row["name"] for row in rows]

    def foreign_keys_on(self) -> bool:
        row = self.one("PRAGMA foreign_keys")
        return bool(row[0]) if row is not None else False

    def __enter__(self) -> Database:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()


def require_table(database: Database, name: str) -> None:
    if name not in database.tables():
        raise ValidationError(f"the database has no {name} table", field="table")
