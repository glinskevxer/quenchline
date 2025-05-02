"""Reading and writing load records.

The trace is not stored here. A trace is thousands of rows per load and belongs
in the file it arrived as, referenced by the load rather than copied into the
database. What the database holds is the record: what went in, where, to which
recipe revision, and what state it reached.

The recipe revision is stored as text alongside the code and is never a foreign
key to a recipe table. A load run in March to revision B stays run to revision
B even if revision B is later withdrawn and deleted, and a foreign key would
either block that deletion or cascade the load away with it.
"""

from __future__ import annotations

from datetime import datetime

from ..errors import ConflictError, NotFoundError
from ..identity import FurnaceTag, LotNumber, WorkOrder
from ..loads.record import Load, LoadState, PartLine
from ..measure import Mass
from .database import Database


def _key(lot: LotNumber | str) -> str:
    """Canonical text for a lot number, however it was written."""
    return str(lot if isinstance(lot, LotNumber) else LotNumber.parse(lot))


class LoadRepository:
    """Load records and the parts on them."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, load: Load) -> None:
        if self.exists(load.lot):
            raise ConflictError("load", str(load.lot))
        self.save(load)

    def save(self, load: Load) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO load_record (lot, work_order, furnace_tag, "
                "recipe_code, recipe_revision, state, weight_lb, charged_at, started_at, "
                "finished_at, trace_source, trace_digest, trace_started) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(load.lot),
                    str(load.work_order),
                    str(load.furnace),
                    load.recipe_code,
                    load.recipe_revision,
                    load.state.value,
                    load.weight.pounds_value if load.weight is not None else None,
                    _stamp(load.charged_at),
                    _stamp(load.started_at),
                    _stamp(load.finished_at),
                    load.trace_source or None,
                    load.trace_digest or None,
                    _stamp(load.trace.started) if load.trace is not None else None,
                ),
            )
            connection.execute("DELETE FROM load_part WHERE lot = ?", (str(load.lot),))
            for line in load.parts:
                connection.execute(
                    "INSERT INTO load_part (lot, part_number, quantity, material, description) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        str(load.lot),
                        line.part_number,
                        line.quantity,
                        line.material,
                        line.description,
                    ),
                )

    def exists(self, lot: LotNumber | str) -> bool:
        return (
            self.database.one("SELECT lot FROM load_record WHERE lot = ?", (_key(lot),))
            is not None
        )

    def get(self, lot: LotNumber | str) -> Load:
        row = self.database.one(
            "SELECT lot, work_order, furnace_tag, recipe_code, recipe_revision, state, "
            "weight_lb, charged_at, started_at, finished_at, trace_source, trace_digest "
            "FROM load_record WHERE lot = ?",
            (_key(lot),),
        )
        if row is None:
            raise NotFoundError("load", _key(lot))
        parts = self.database.query(
            "SELECT part_number, quantity, material, description FROM load_part "
            "WHERE lot = ? ORDER BY part_number",
            (_key(lot),),
        )
        return Load(
            lot=LotNumber.parse(row["lot"]),
            work_order=WorkOrder.parse(row["work_order"]),
            furnace=FurnaceTag.parse(row["furnace_tag"]),
            recipe_code=row["recipe_code"],
            recipe_revision=row["recipe_revision"],
            parts=tuple(
                PartLine(p["part_number"], p["quantity"], p["material"], p["description"])
                for p in parts
            ),
            weight=Mass.pounds(row["weight_lb"]) if row["weight_lb"] is not None else None,
            state=LoadState(row["state"]),
            charged_at=_read(row["charged_at"]),
            started_at=_read(row["started_at"]),
            finished_at=_read(row["finished_at"]),
            trace_source=row["trace_source"] or "",
            trace_digest=row["trace_digest"] or "",
        )

    def all(self) -> list[Load]:
        rows = self.database.query("SELECT lot FROM load_record ORDER BY lot")
        return [self.get(row["lot"]) for row in rows]

    def in_state(self, state: LoadState) -> list[Load]:
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE state = ? ORDER BY lot", (state.value,)
        )
        return [self.get(row["lot"]) for row in rows]

    def on_furnace(self, furnace: FurnaceTag | str) -> list[Load]:
        tag = furnace if isinstance(furnace, FurnaceTag) else FurnaceTag.parse(furnace)
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE furnace_tag = ? ORDER BY lot", (str(tag),)
        )
        return [self.get(row["lot"]) for row in rows]

    def for_work_order(self, work_order: WorkOrder | str) -> list[Load]:
        order = work_order if isinstance(work_order, WorkOrder) else WorkOrder.parse(work_order)
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE work_order = ? ORDER BY lot",
            (str(order),),
        )
        return [self.get(row["lot"]) for row in rows]

    def to_recipe(self, code: str, revision: str | None = None) -> list[Load]:
        if revision is None:
            rows = self.database.query(
                "SELECT lot FROM load_record WHERE recipe_code = ? ORDER BY lot", (code,)
            )
        else:
            rows = self.database.query(
                "SELECT lot FROM load_record WHERE recipe_code = ? AND recipe_revision = ? "
                "ORDER BY lot",
                (code, revision),
            )
        return [self.get(row["lot"]) for row in rows]

    def between(self, start: datetime, end: datetime) -> list[Load]:
        """Loads that finished inside a window."""
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE finished_at IS NOT NULL "
            "AND finished_at >= ? AND finished_at <= ? ORDER BY finished_at",
            (_stamp(start), _stamp(end)),
        )
        return [self.get(row["lot"]) for row in rows]

    def delete(self, lot: LotNumber | str) -> None:
        if not self.exists(lot):
            raise NotFoundError("load", _key(lot))
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM load_part WHERE lot = ?", (_key(lot),))
            connection.execute("DELETE FROM load_record WHERE lot = ?", (_key(lot),))

    def with_trace_digest(self, digest: str) -> list[Load]:
        """Loads already carrying one logger file, so it is not attached twice."""
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE trace_digest = ? ORDER BY lot", (digest,)
        )
        return [self.get(row["lot"]) for row in rows]

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM load_record")
        return int(row["n"]) if row is not None else 0

    def piece_count(self) -> int:
        row = self.database.one("SELECT COALESCE(SUM(quantity), 0) AS n FROM load_part")
        return int(row["n"]) if row is not None else 0


def _stamp(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat(timespec="seconds")


def _read(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)
