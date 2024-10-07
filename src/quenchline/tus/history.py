"""The survey history for one furnace zone, and the range it earns.

A furnace is not qualified because somebody wrote a number on a sign. It is
qualified because a survey passed at the bottom of the range and another passed
at the top, and everything in between is covered by the pair. That is the whole
idea and it has two edges worth stating.

**A single set point earns very little.** One survey at 1550 does not qualify a
furnace from 1400 to 1700. It qualifies a narrow band either side of 1550, wide
enough to be useful and no wider, because there is no evidence about 1700.

**A failure at one set point does not only cost that set point.** A survey that
passed at 1200 and failed at 1700 has proved the furnace uniform at 1200 and
proved it is not uniform at 1700, so the qualified range collapses to the part
that passed rather than staying where it was.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..calendar_rules import DueRule, Interval, days_until, due_date, is_overdue
from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass, InstrumentationType, tus_interval
from ..furnaces.zones import QualifiedRange
from ..identity import FurnaceTag
from ..temperature import Scale, Temperature, TemperatureDelta

SINGLE_POINT_MARGIN = TemperatureDelta(25.0, Scale.FAHRENHEIT)


@dataclass(frozen=True)
class SurveyOutcome:
    """A survey reduced to what the history cares about."""

    number: str
    performed: date
    passed: bool
    passing_setpoints: tuple[Temperature, ...]
    failing_setpoints: tuple[Temperature, ...] = ()

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("survey number is blank", field="number")
        if self.passed and self.failing_setpoints:
            raise ValidationError(
                "a passing survey cannot carry failing set points", field="passed"
            )


@dataclass(frozen=True)
class SurveyDue:
    """When the next survey is due on one zone."""

    furnace: FurnaceTag
    zone: str
    last_passed: date | None
    due: date | None
    days_left: int | None
    overdue: bool
    interval: Interval

    @property
    def never_surveyed(self) -> bool:
        return self.last_passed is None


def range_from(setpoints: tuple[Temperature, ...]) -> QualifiedRange | None:
    """The range a set of passing set points earns."""
    if not setpoints:
        return None
    if len(setpoints) == 1:
        only = setpoints[0]
        return QualifiedRange(only.minus(SINGLE_POINT_MARGIN), only + SINGLE_POINT_MARGIN)
    return QualifiedRange.spanning(list(setpoints))


@dataclass
class SurveyHistory:
    """Every survey on one furnace zone, oldest first."""

    furnace: FurnaceTag
    zone: str
    furnace_class: FurnaceClass
    instrumentation: InstrumentationType
    outcomes: list[SurveyOutcome] = field(default_factory=list)

    def file(self, outcome: SurveyOutcome) -> None:
        if any(o.number == outcome.number for o in self.outcomes):
            raise ValidationError(f"survey {outcome.number} is already on file", field="number")
        self.outcomes.append(outcome)
        self.outcomes.sort(key=lambda o: o.performed)

    @property
    def is_empty(self) -> bool:
        return not self.outcomes

    def latest(self) -> SurveyOutcome | None:
        return self.outcomes[-1] if self.outcomes else None

    def latest_pass(self) -> SurveyOutcome | None:
        passes = [o for o in self.outcomes if o.passed]
        return passes[-1] if passes else None

    def consecutive_passes(self) -> int:
        run = 0
        for outcome in reversed(self.outcomes):
            if not outcome.passed:
                break
            run += 1
        return run

    def interval(self) -> Interval:
        return tus_interval(
            self.furnace_class,
            self.instrumentation,
            consecutive_passes=self.consecutive_passes(),
        )

    def due(
        self, on: date, *, rule: DueRule = DueRule.ANNIVERSARY, grace: int = 0
    ) -> SurveyDue:
        latest = self.latest_pass()
        interval = self.interval()
        if latest is None:
            return SurveyDue(self.furnace, self.zone, None, None, None, True, interval)
        due_on = due_date(latest.performed, interval, rule)
        return SurveyDue(
            self.furnace,
            self.zone,
            latest.performed,
            due_on,
            days_until(due_on, on),
            is_overdue(due_on, on, grace=grace),
            interval,
        )

    def in_date(self, on: date, *, grace: int = 0) -> bool:
        return not self.due(on, grace=grace).overdue

    def qualified(self) -> QualifiedRange | None:
        """The range the most recent survey leaves the furnace holding.

        Only the newest survey counts. An older survey that reached higher is
        not evidence about the furnace as it is today, which is the whole reason
        the survey has an interval in the first place.
        """
        latest = self.latest()
        if latest is None:
            return None
        return range_from(latest.passing_setpoints)

    def may_run(self, at: Temperature, on: date, *, grace: int = 0) -> bool:
        if not self.in_date(on, grace=grace):
            return False
        qualified = self.qualified()
        return qualified is not None and qualified.covers(at)
