"""Reading and writing survey outcomes.

The survey itself, thousands of readings across a dozen positions, stays in the
files it arrived as. What is stored is the outcome, and the outcome is not one
verdict: it is a verdict **per set point**, because a survey that passed at 1200
and failed at 1700 leaves the furnace qualified over part of its range and that
is exactly the case the register has to get right.

So there are two tables and the second one is the point of the first.
"""

from __future__ import annotations

from datetime import date

from ..errors import ConflictError, NotFoundError
from ..furnaces.classes import FurnaceClass, InstrumentationType
from ..identity import FurnaceTag
from ..temperature import Temperature
from ..tus.history import SurveyHistory, SurveyOutcome
from .database import Database


class SurveyRepository:
    """Survey outcomes, kept per set point."""

    def __init__(self, database: Database) -> None:
        self.database = database

    def insert(self, outcome: SurveyOutcome, furnace: FurnaceTag | str, zone: str) -> None:
        if self.exists(outcome.number):
            raise ConflictError("survey", outcome.number)
        self.save(outcome, furnace, zone)

    def save(self, outcome: SurveyOutcome, furnace: FurnaceTag | str, zone: str) -> None:
        tag = furnace if isinstance(furnace, FurnaceTag) else FurnaceTag.parse(furnace)
        with self.database.transaction() as connection:
            connection.execute(
                "INSERT OR REPLACE INTO survey_outcome (number, furnace_tag, zone, "
                "performed, passed) VALUES (?, ?, ?, ?, ?)",
                (
                    outcome.number,
                    str(tag),
                    zone,
                    outcome.performed.isoformat(),
                    int(outcome.passed),
                ),
            )
            connection.execute(
                "DELETE FROM survey_setpoint WHERE survey_number = ?", (outcome.number,)
            )
            for setpoint in outcome.passing_setpoints:
                connection.execute(
                    "INSERT INTO survey_setpoint (survey_number, setpoint_f, passed) "
                    "VALUES (?, ?, 1)",
                    (outcome.number, setpoint.degf),
                )
            for setpoint in outcome.failing_setpoints:
                connection.execute(
                    "INSERT INTO survey_setpoint (survey_number, setpoint_f, passed) "
                    "VALUES (?, ?, 0)",
                    (outcome.number, setpoint.degf),
                )

    def exists(self, number: str) -> bool:
        return (
            self.database.one("SELECT number FROM survey_outcome WHERE number = ?", (number,))
            is not None
        )

    def get(self, number: str) -> SurveyOutcome:
        row = self.database.one("SELECT * FROM survey_outcome WHERE number = ?", (number,))
        if row is None:
            raise NotFoundError("survey", number)
        return self._build(row)

    def zones(self) -> list[tuple[str, str]]:
        """Every furnace and zone that has ever been surveyed."""
        rows = self.database.query(
            "SELECT DISTINCT furnace_tag, zone FROM survey_outcome ORDER BY furnace_tag, zone"
        )
        return [(row["furnace_tag"], row["zone"]) for row in rows]

    def for_zone(self, furnace: FurnaceTag | str, zone: str) -> list[SurveyOutcome]:
        tag = furnace if isinstance(furnace, FurnaceTag) else FurnaceTag.parse(furnace)
        rows = self.database.query(
            "SELECT * FROM survey_outcome WHERE furnace_tag = ? AND zone = ? "
            "ORDER BY performed, number",
            (str(tag), zone),
        )
        return [self._build(row) for row in rows]

    def history(
        self,
        furnace: FurnaceTag | str,
        zone: str,
        furnace_class: FurnaceClass,
        instrumentation: InstrumentationType,
    ) -> SurveyHistory:
        tag = furnace if isinstance(furnace, FurnaceTag) else FurnaceTag.parse(furnace)
        history = SurveyHistory(tag, zone, furnace_class, instrumentation)
        for outcome in self.for_zone(tag, zone):
            history.file(outcome)
        return history

    def delete(self, number: str) -> None:
        if not self.exists(number):
            raise NotFoundError("survey", number)
        with self.database.transaction() as connection:
            connection.execute("DELETE FROM survey_setpoint WHERE survey_number = ?", (number,))
            connection.execute("DELETE FROM survey_outcome WHERE number = ?", (number,))

    def count(self) -> int:
        row = self.database.one("SELECT COUNT(*) AS n FROM survey_outcome")
        return int(row["n"]) if row is not None else 0

    def _build(self, row: object) -> SurveyOutcome:
        mapping = dict(row)  # type: ignore[call-overload]
        points = self.database.query(
            "SELECT setpoint_f, passed FROM survey_setpoint WHERE survey_number = ? "
            "ORDER BY setpoint_f",
            (mapping["number"],),
        )
        return SurveyOutcome(
            number=mapping["number"],
            performed=date.fromisoformat(mapping["performed"]),
            passed=bool(mapping["passed"]),
            passing_setpoints=tuple(
                Temperature.fahrenheit(point["setpoint_f"])
                for point in points
                if point["passed"]
            ),
            failing_setpoints=tuple(
                Temperature.fahrenheit(point["setpoint_f"])
                for point in points
                if not point["passed"]
            ),
        )
