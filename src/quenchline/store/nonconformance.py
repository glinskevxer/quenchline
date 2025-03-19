"""Reading and writing nonconformance reports.

Reports are stored flat. The entries a report accumulates as it moves along are
deliberately not stored: they are a running commentary, they are written on the
paper copy, and a database column full of free text that nobody queries is a
column that eventually holds a customer's name and a legal problem.

What is stored is everything a query needs: the subject, the reference, the
stage, the disposition and the suspect window. That is enough to answer "what is
open", "what is old" and "which loads does this throw into doubt", which are the
three questions anybody actually asks.
"""

from __future__ import annotations

from datetime import date

from ..errors import ConflictError, NotFoundError
from ..loads.disposition import Disposition
from ..nonconformance.record import NcrStage, NcrSubject, Nonconformance
from .database import Database


class NcrRepository:
    """Nonconformance reports."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, report: Nonconformance) -> None:
        if self.exists(report.number):
            raise ConflictError("nonconformance", report.number)
        self.save(report)

    def save(self, report: Nonconformance) -> None:
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO nonconformance (number, subject, reference, "
                "raised_on, summary, stage, disposition, suspect_from, suspect_to) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    report.number,
                    report.subject.value,
                    report.reference,
                    report.raised_on.isoformat(),
                    report.summary,
                    report.stage.value,
                    report.disposition.value if report.disposition is not None else None,
                    report.suspect_from.isoformat() if report.suspect_from else None,
                    report.suspect_to.isoformat() if report.suspect_to else None,
                ),
            )

    def exists(self, number: str) -> bool:
        return (
            self.database.one("SELECT number FROM nonconformance WHERE number = ?", (number,))
            is not None
        )

    def get(self, number: str) -> Nonconformance:
        row = self.database.one(
            "SELECT number, subject, reference, raised_on, summary, stage, disposition, "
            "suspect_from, suspect_to FROM nonconformance WHERE number = ?",
            (number,),
        )
        if row is None:
            raise NotFoundError("nonconformance", number)
        return Nonconformance(
            number=row["number"],
            subject=NcrSubject(row["subject"]),
            reference=row["reference"],
            raised_on=date.fromisoformat(row["raised_on"]),
            summary=row["summary"],
            stage=NcrStage(row["stage"]),
            disposition=(
                Disposition(row["disposition"]) if row["disposition"] is not None else None
            ),
            suspect_from=(
                date.fromisoformat(row["suspect_from"]) if row["suspect_from"] else None
            ),
            suspect_to=date.fromisoformat(row["suspect_to"]) if row["suspect_to"] else None,
        )

    def all(self) -> list[Nonconformance]:
        rows = self.database.query("SELECT number FROM nonconformance ORDER BY number")
        return [self.get(row["number"]) for row in rows]

    def open_reports(self) -> list[Nonconformance]:
        stages = [s.value for s in NcrStage if s.is_open]
        placeholders = ", ".join("?" for _ in stages)
        rows = self.database.query(
            f"SELECT number FROM nonconformance WHERE stage IN ({placeholders}) "
            "ORDER BY number",
            tuple(stages),
        )
        return [self.get(row["number"]) for row in rows]

    def about(self, subject: NcrSubject) -> list[Nonconformance]:
        rows = self.database.query(
            "SELECT number FROM nonconformance WHERE subject = ? ORDER BY number",
            (subject.value,),
        )
        return [self.get(row["number"]) for row in rows]

    def against(self, reference: str) -> list[Nonconformance]:
        rows = self.database.query(
            "SELECT number FROM nonconformance WHERE reference = ? ORDER BY number",
            (reference,),
        )
        return [self.get(row["number"]) for row in rows]

    def raised_between(self, start: date, end: date) -> list[Nonconformance]:
        rows = self.database.query(
            "SELECT number FROM nonconformance WHERE raised_on >= ? AND raised_on <= ? "
            "ORDER BY raised_on, number",
            (start.isoformat(), end.isoformat()),
        )
        return [self.get(row["number"]) for row in rows]

    def with_suspect_windows(self) -> list[Nonconformance]:
        rows = self.database.query(
            "SELECT number FROM nonconformance WHERE suspect_from IS NOT NULL ORDER BY number"
        )
        return [self.get(row["number"]) for row in rows]

    def delete(self, number: str) -> None:
        if not self.exists(number):
            raise NotFoundError("nonconformance", number)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM nonconformance WHERE number = ?", (number,))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM nonconformance")
        return int(row["n"]) if row is not None else 0

    def next_number(self, year: int) -> str:
        """The next report number for a year, in the shop's own format."""
        prefix = f"NCR-{year % 100:02d}-"
        row = self.database.one(
            "SELECT number FROM nonconformance WHERE number LIKE ? "
            "ORDER BY number DESC LIMIT 1",
            (f"{prefix}%",),
        )
        if row is None:
            return f"{prefix}001"
        tail = row["number"][len(prefix) :]
        return f"{prefix}{int(tail) + 1:03d}"
