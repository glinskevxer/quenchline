"""Storing what grading a run found.

The findings are recomputed from the trace every time somebody asks, and that is
right: the rules change and a stored verdict from before a rule changed is a
lie. What is stored here is the **grading event** rather than the verdict, so
the shop can answer the questions that need history rather than truth:

* which loads have been graded at all, and which are still waiting;
* what the shop's commonest deviation was last quarter;
* which furnace produces them.

That last one is the reason this table exists. A short soak on one furnace is a
bad day. The same short soak on the same furnace forty times is a broken
recirculating fan, and nothing that looks at one load at a time will ever say so.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date

from ..errors import NotFoundError
from ..loads.deviation import Deviation, DeviationKind, Severity
from ..loads.disposition import Decision, Disposition
from ..loads.record import Load
from .database import Database
from .keys import lot_key


@dataclass(frozen=True)
class GradedRun:
    """One grading of one load."""

    lot: str
    graded_on: date
    recipe_code: str
    recipe_revision: str
    disposition: Disposition
    reason: str
    findings: tuple[Deviation, ...]

    @property
    def recipe(self) -> str:
        return f"{self.recipe_code} rev {self.recipe_revision}"

    @property
    def worst(self) -> Severity | None:
        if not self.findings:
            return None
        return max((f.severity for f in self.findings), key=lambda s: s.rank)


class GradingRepository:
    """Grading events and the findings they produced."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def record(
        self,
        load: Load,
        findings: tuple[Deviation, ...],
        decision: Decision,
        on: date,
    ) -> None:
        """Replace whatever grading was on file for this load."""
        lot = lot_key(load.lot)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM graded_finding WHERE lot = ?", (lot,))
            connection.execute(
                "INSERT OR REPLACE INTO graded_run (lot, graded_on, recipe_code, "
                "recipe_revision, disposition, reason) VALUES (?, ?, ?, ?, ?, ?)",
                (
                    lot,
                    on.isoformat(),
                    load.recipe_code,
                    load.recipe_revision,
                    decision.disposition.value,
                    decision.reason,
                ),
            )
            for finding in findings:
                connection.execute(
                    "INSERT INTO graded_finding (lot, kind, step, severity, detail) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        lot,
                        finding.kind.value,
                        finding.step,
                        finding.severity.value,
                        finding.detail,
                    ),
                )

    def exists(self, lot: str) -> bool:
        return (
            self.database.one("SELECT lot FROM graded_run WHERE lot = ?", (lot_key(lot),))
            is not None
        )

    def get(self, lot: str) -> GradedRun:
        key = lot_key(lot)
        row = self.database.one("SELECT * FROM graded_run WHERE lot = ?", (key,))
        if row is None:
            raise NotFoundError("graded run", key)
        return self._build(row)

    def all(self) -> list[GradedRun]:
        rows = self.database.query("SELECT * FROM graded_run ORDER BY lot")
        return [self._build(row) for row in rows]

    def with_disposition(self, disposition: Disposition) -> list[GradedRun]:
        rows = self.database.query(
            "SELECT * FROM graded_run WHERE disposition = ? ORDER BY lot",
            (disposition.value,),
        )
        return [self._build(row) for row in rows]

    def ungraded(self) -> list[str]:
        """Finished loads nobody has graded yet."""
        rows = self.database.query(
            "SELECT lot FROM load_record WHERE finished_at IS NOT NULL "
            "AND lot NOT IN (SELECT lot FROM graded_run) ORDER BY lot"
        )
        return [row["lot"] for row in rows]

    def counts_by_kind(self) -> dict[str, int]:
        rows = self.database.query(
            "SELECT kind, COUNT(*) AS n FROM graded_finding GROUP BY kind ORDER BY n DESC, kind"
        )
        return {row["kind"]: int(row["n"]) for row in rows}

    def counts_by_furnace(self, kind: DeviationKind | None = None) -> dict[str, int]:
        """Which furnaces produce the findings, which is what a fault looks like."""
        if kind is None:
            rows = self.database.query(
                "SELECT l.furnace_tag AS tag, COUNT(*) AS n FROM graded_finding f "
                "JOIN load_record l ON l.lot = f.lot GROUP BY tag ORDER BY n DESC, tag"
            )
        else:
            rows = self.database.query(
                "SELECT l.furnace_tag AS tag, COUNT(*) AS n FROM graded_finding f "
                "JOIN load_record l ON l.lot = f.lot WHERE f.kind = ? "
                "GROUP BY tag ORDER BY n DESC, tag",
                (kind.value,),
            )
        return {row["tag"]: int(row["n"]) for row in rows}

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM graded_run")
        return int(row["n"]) if row is not None else 0

    def finding_count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM graded_finding")
        return int(row["n"]) if row is not None else 0

    def _build(self, row: object) -> GradedRun:
        mapping = dict(row)  # type: ignore[call-overload]
        findings = self.database.query(
            "SELECT kind, step, severity, detail FROM graded_finding WHERE lot = ? ORDER BY id",
            (mapping["lot"],),
        )
        return GradedRun(
            lot=mapping["lot"],
            graded_on=date.fromisoformat(mapping["graded_on"]),
            recipe_code=mapping["recipe_code"],
            recipe_revision=mapping["recipe_revision"],
            disposition=Disposition(mapping["disposition"]),
            reason=mapping["reason"],
            findings=tuple(
                Deviation(
                    DeviationKind(f["kind"]),
                    f["step"],
                    f["detail"],
                    Severity(f["severity"]),
                )
                for f in findings
            ),
        )
