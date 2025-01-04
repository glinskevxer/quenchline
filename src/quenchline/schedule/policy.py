"""One schedule for everything that comes due.

Calibrations, system accuracy tests, uniformity surveys and bath checks all live
in their own modules with their own rules, and that is right, because the rules
genuinely differ. What is wrong is making the shop look in four places to find
out what is due on Monday.

So this is a thin layer with one job: take a due date from anywhere, put it on
one list, and rank it. The ranking is the only real decision here, and it is not
just "sort by date", because the consequence of missing one of these is not the
same for all of them.

An overdue **survey** stops the furnace. An overdue **bath check** stops the
quench. An overdue **calibration** stops the instrument, and if it was the
controlling instrument it stops the furnace too. So an item's urgency depends on
what it blocks as well as on how late it is, and a bath check three days late
outranks a monitoring instrument three weeks late.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..calendar_rules import days_until, is_overdue
from ..errors import ValidationError


class Activity(Enum):
    """The kinds of thing that come due."""

    INSTRUMENT_CALIBRATION = "instrument_calibration"
    SENSOR_CALIBRATION = "sensor_calibration"
    SYSTEM_ACCURACY_TEST = "system_accuracy_test"
    UNIFORMITY_SURVEY = "uniformity_survey"
    BATH_CHECK = "bath_check"

    @property
    def stops_the_furnace(self) -> bool:
        return self in {
            Activity.SYSTEM_ACCURACY_TEST,
            Activity.UNIFORMITY_SURVEY,
        }

    @property
    def weight(self) -> int:
        """How much being late costs, higher is worse."""
        if self is Activity.UNIFORMITY_SURVEY:
            return 4
        if self is Activity.SYSTEM_ACCURACY_TEST:
            return 3
        if self is Activity.BATH_CHECK:
            return 2
        return 1


class Urgency(Enum):
    OVERDUE = "overdue"
    DUE_NOW = "due_now"
    DUE_SOON = "due_soon"
    SCHEDULED = "scheduled"
    NEVER_DONE = "never_done"

    @property
    def needs_attention(self) -> bool:
        return self in {Urgency.OVERDUE, Urgency.DUE_NOW, Urgency.NEVER_DONE}

    @property
    def rank(self) -> int:
        order = ["never_done", "overdue", "due_now", "due_soon", "scheduled"]
        return order.index(self.value)


DUE_SOON_DAYS = 14


def urgency_of(
    due: date | None, on: date, *, grace: int = 0, soon: int = DUE_SOON_DAYS
) -> Urgency:
    """Where one due date sits relative to today."""
    if soon < 0:
        raise ValidationError("the soon window cannot be negative", field="soon")
    if due is None:
        return Urgency.NEVER_DONE
    if is_overdue(due, on, grace=grace):
        return Urgency.OVERDUE
    left = days_until(due, on)
    if left <= 0:
        return Urgency.DUE_NOW
    if left <= soon:
        return Urgency.DUE_SOON
    return Urgency.SCHEDULED


@dataclass(frozen=True)
class DueItem:
    """One thing that comes due, from any of the registers."""

    activity: Activity
    subject: str
    due: date | None
    urgency: Urgency
    days_left: int | None
    detail: str = ""

    @classmethod
    def of(
        cls,
        activity: Activity,
        subject: str,
        due: date | None,
        on: date,
        *,
        grace: int = 0,
        soon: int = DUE_SOON_DAYS,
        detail: str = "",
    ) -> DueItem:
        urgency = urgency_of(due, on, grace=grace, soon=soon)
        left = None if due is None else days_until(due, on)
        return cls(activity, subject, due, urgency, left, detail)

    @property
    def needs_attention(self) -> bool:
        return self.urgency.needs_attention

    @property
    def score(self) -> tuple[int, int, int]:
        """Sort key: urgency first, then what it blocks, then how late."""
        lateness = 0 if self.days_left is None else -min(0, self.days_left)
        return (self.urgency.rank, -self.activity.weight, -lateness)

    def __str__(self) -> str:
        when = self.due.isoformat() if self.due else "never done"
        return f"{self.activity.value} {self.subject}: {when} ({self.urgency.value})"


def rank(items: list[DueItem]) -> list[DueItem]:
    """Worst first, then by what being late blocks, then by how late."""
    return sorted(items, key=lambda item: (item.score, item.subject))


def attention(items: list[DueItem]) -> list[DueItem]:
    return [item for item in rank(items) if item.needs_attention]


def by_activity(items: list[DueItem]) -> dict[Activity, list[DueItem]]:
    grouped: dict[Activity, list[DueItem]] = {activity: [] for activity in Activity}
    for item in rank(items):
        grouped[item.activity].append(item)
    return grouped
