"""Due date arithmetic.

Everything with a calibration sticker on it has a next due date, and the shop
does not compute those the same way for everything. Three rules are in use, and
which one applies is a property of the thing being scheduled rather than of the
date:

``ANNIVERSARY``
    due exactly one interval after the last event. A quarterly SAT done on the
    14th is due again on the 14th.

``END_OF_MONTH``
    due on the last day of the month the anniversary falls in. This is what the
    customer specifications mean when they say "due within the calendar month",
    and it is why a job done on the 2nd and one done on the 27th of the same
    month come due together.

``START_OF_MONTH``
    due on the first day of the month after the anniversary month. A stricter
    reading of the same clause, used by two of our aerospace customers.

Month arithmetic clamps rather than rolling over: 31 January plus one month is
28 February, not 3 March. Rolling over is how a survey silently gains three days
of life every time it lands on a long month.
"""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from .errors import ValidationError


class IntervalUnit(Enum):
    DAY = "day"
    WEEK = "week"
    MONTH = "month"
    YEAR = "year"


class DueRule(Enum):
    ANNIVERSARY = "anniversary"
    END_OF_MONTH = "end_of_month"
    START_OF_MONTH = "start_of_month"


def days_in_month(year: int, month: int) -> int:
    return calendar.monthrange(year, month)[1]


def end_of_month(day: date) -> date:
    return date(day.year, day.month, days_in_month(day.year, day.month))


def start_of_month(day: date) -> date:
    return date(day.year, day.month, 1)


def add_months(day: date, count: int) -> date:
    """Add whole months, clamping the day of month rather than rolling over."""
    total = day.month - 1 + count
    year = day.year + total // 12
    month = total % 12 + 1
    return date(year, month, min(day.day, days_in_month(year, month)))


@dataclass(frozen=True)
class Interval:
    """A scheduling interval, such as "three months" or "14 days"."""

    count: int
    unit: IntervalUnit

    def __post_init__(self) -> None:
        if self.count <= 0:
            raise ValidationError("interval must be positive", field="count")

    @classmethod
    def days(cls, count: int) -> Interval:
        return cls(count, IntervalUnit.DAY)

    @classmethod
    def weeks(cls, count: int) -> Interval:
        return cls(count, IntervalUnit.WEEK)

    @classmethod
    def months(cls, count: int) -> Interval:
        return cls(count, IntervalUnit.MONTH)

    @classmethod
    def years(cls, count: int) -> Interval:
        return cls(count, IntervalUnit.YEAR)

    def after(self, start: date) -> date:
        if self.unit is IntervalUnit.DAY:
            return start + timedelta(days=self.count)
        if self.unit is IntervalUnit.WEEK:
            return start + timedelta(weeks=self.count)
        if self.unit is IntervalUnit.MONTH:
            return add_months(start, self.count)
        return add_months(start, self.count * 12)

    def scaled(self, factor: float) -> Interval:
        """A longer or shorter interval of the same unit, rounded down."""
        scaled = int(self.count * factor)
        if scaled < 1:
            raise ValidationError("scaling emptied the interval", field="factor")
        return Interval(scaled, self.unit)

    @property
    def approximate_days(self) -> int:
        """Only for sorting and reporting. Never use it to compute a due date."""
        if self.unit is IntervalUnit.DAY:
            return self.count
        if self.unit is IntervalUnit.WEEK:
            return self.count * 7
        if self.unit is IntervalUnit.MONTH:
            return self.count * 30
        return self.count * 365

    def __str__(self) -> str:
        plural = "" if self.count == 1 else "s"
        return f"{self.count} {self.unit.value}{plural}"


def due_date(last: date, interval: Interval, rule: DueRule = DueRule.ANNIVERSARY) -> date:
    """The next due date after ``last``."""
    anniversary = interval.after(last)
    if rule is DueRule.ANNIVERSARY:
        return anniversary
    if rule is DueRule.END_OF_MONTH:
        return end_of_month(anniversary)
    return start_of_month(add_months(anniversary, 1))


def days_until(due: date, today: date) -> int:
    """Positive while there is time left, negative once it is overdue."""
    return (due - today).days


def is_overdue(due: date, today: date, *, grace: int = 0) -> bool:
    if grace < 0:
        raise ValidationError("grace cannot be negative", field="grace")
    return days_until(due, today) < -grace


def clamp_to_month_end(day: date) -> date:
    """Pull a date that fell past its month end back onto the last valid day."""
    last = days_in_month(day.year, day.month)
    return date(day.year, day.month, min(day.day, last))
