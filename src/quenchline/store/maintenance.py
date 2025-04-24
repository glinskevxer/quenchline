"""Looking after the database file.

Four jobs, none of them clever, all of them the sort of thing that gets left
undone until the day it matters.

**Integrity check** asks SQLite whether the file is internally consistent. It is
cheap on a database this size and it is the only warning of a failing disk that
arrives before the data is gone.

**Foreign key check** is separate and is not implied by the integrity check. A
file that was written by a version with foreign keys switched off can be
perfectly well formed and still hold a work zone pointing at a furnace that is
not there.

**Vacuum** reclaims space. It rewrites the whole file, so it is a thing to do on
a Sunday rather than between two loads.

**Backup** uses SQLite's own online backup rather than copying the file, because
copying a file that a writer has open produces something that looks like a
database and is not one.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from pathlib import Path

from ..errors import ValidationError
from .database import Database


@dataclass(frozen=True)
class IntegrityReport:
    """What the checks found."""

    integrity: tuple[str, ...]
    foreign_keys: tuple[str, ...]

    @property
    def is_clean(self) -> bool:
        return self.integrity == ("ok",) and not self.foreign_keys

    @property
    def problems(self) -> tuple[str, ...]:
        found: list[str] = []
        if self.integrity != ("ok",):
            found.extend(self.integrity)
        found.extend(self.foreign_keys)
        return tuple(found)

    def __str__(self) -> str:
        if self.is_clean:
            return "database is clean"
        return f"{len(self.problems)} problem(s): " + "; ".join(self.problems)


def check(database: Database) -> IntegrityReport:
    """Run both checks and report what they said."""
    integrity = tuple(str(row[0]) for row in database.query("PRAGMA integrity_check"))
    orphans = tuple(
        f"{row[0]} row references missing {row[2]}"
        for row in database.query("PRAGMA foreign_key_check")
    )
    return IntegrityReport(integrity, orphans)


def vacuum(database: Database) -> None:
    """Rewrite the file, reclaiming free pages."""
    database.connection.execute("VACUUM")


def size_of(path: Path) -> int:
    if not path.exists():
        raise ValidationError(f"no database at {path}", field="path")
    return path.stat().st_size


def page_stats(database: Database) -> dict[str, int]:
    """Page counts, which is what a vacuum actually moves."""
    stats: dict[str, int] = {}
    for pragma in ("page_count", "freelist_count", "page_size"):
        row = database.one(f"PRAGMA {pragma}")
        stats[pragma] = int(row[0]) if row is not None else 0
    return stats


def row_counts(database: Database) -> dict[str, int]:
    """How many rows are in each table, for a status line."""
    counts: dict[str, int] = {}
    for table in database.tables():
        row = database.one(f"SELECT COUNT(*) AS n FROM {table}")
        counts[table] = int(row["n"]) if row is not None else 0
    return counts


def backup(database: Database, destination: Path) -> Path:
    """Take a consistent copy of an open database."""
    if destination.exists():
        raise ValidationError(f"{destination} already exists", field="destination")
    destination.parent.mkdir(parents=True, exist_ok=True)
    target = sqlite3.connect(str(destination))
    try:
        database.connection.backup(target)
    finally:
        target.close()
    return destination


def restore(source: Path, destination: Path, *, overwrite: bool = False) -> Path:
    """Put a backup back, refusing to clobber unless told to."""
    if not source.exists():
        raise ValidationError(f"no backup at {source}", field="source")
    if destination.exists() and not overwrite:
        raise ValidationError(
            f"{destination} exists, pass overwrite to replace it", field="destination"
        )
    origin = sqlite3.connect(str(source))
    target = sqlite3.connect(str(destination))
    try:
        origin.backup(target)
    finally:
        origin.close()
        target.close()
    return destination
