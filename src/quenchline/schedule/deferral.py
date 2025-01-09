"""Deferring something that is due.

Sometimes a survey cannot happen this week because the furnace is in pieces, and
the honest thing is to write down that it slipped and who agreed to it, rather
than quietly letting it go overdue.

Three rules keep a deferral from being a way of never doing the work:

* **some things cannot be deferred at all.** A uniformity survey on a precision
  furnace is one. A system accuracy test on a furnace running aerospace work is
  another, and that one is a property of the work rather than of the furnace, so
  it is passed in.
* **there is a ceiling on how far**, and it is shorter for the things that stop
  a furnace than for the things that stop one instrument.
* **a long deferral needs a second signature.** Not a different rule, just a
  higher bar, and it is checked here rather than left to whoever is filling the
  form in.

A subject can only have one deferral open at a time. Stacking them is how a
three week slip becomes a nine month one.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, timedelta
from enum import Enum

from ..errors import ConflictError, StateError, ValidationError
from .policy import Activity

MAX_DAYS: dict[str, int] = {
    "instrument_calibration": 30,
    "sensor_calibration": 30,
    "system_accuracy_test": 14,
    "uniformity_survey": 21,
    "bath_check": 7,
}

SECOND_SIGNATURE_OVER = 14


class DeferralState(Enum):
    OPEN = "open"
    USED = "used"
    CANCELLED = "cancelled"

    @property
    def is_open(self) -> bool:
        return self is DeferralState.OPEN


@dataclass(frozen=True)
class Deferral:
    """One agreed slip of one due date."""

    activity: Activity
    subject: str
    original_due: date
    days: int
    approved_by: str
    approved_on: date
    reason: str
    countersigned_by: str = ""
    state: DeferralState = DeferralState.OPEN

    def __post_init__(self) -> None:
        if self.days < 1:
            raise ValidationError("a deferral has to move the date", field="days")
        if not self.approved_by.strip():
            raise ValidationError("a deferral needs an approver", field="approved_by")
        if not self.reason.strip():
            raise ValidationError("a deferral needs a reason", field="reason")

    @property
    def new_due(self) -> date:
        return self.original_due + timedelta(days=self.days)

    @property
    def needs_countersignature(self) -> bool:
        return self.days > SECOND_SIGNATURE_OVER

    @property
    def is_signed(self) -> bool:
        if not self.needs_countersignature:
            return True
        return bool(self.countersigned_by.strip())

    def covers(self, on: date) -> bool:
        return self.state.is_open and on <= self.new_due

    def __str__(self) -> str:
        return (
            f"{self.activity.value} {self.subject} deferred {self.days} days "
            f"to {self.new_due.isoformat()}"
        )


def deferrable(activity: Activity, *, precision_furnace: bool, aerospace: bool) -> bool:
    """Whether this activity may be deferred at all in this situation."""
    if activity is Activity.UNIFORMITY_SURVEY and precision_furnace:
        return False
    return not (activity is Activity.SYSTEM_ACCURACY_TEST and aerospace)


def maximum_days(activity: Activity) -> int:
    return MAX_DAYS[activity.value]


@dataclass
class DeferralRegister:
    """Every deferral the shop has agreed."""

    deferrals: list[Deferral] = field(default_factory=list)

    def open_for(self, activity: Activity, subject: str) -> Deferral | None:
        for deferral in self.deferrals:
            if (
                deferral.activity is activity
                and deferral.subject == subject
                and deferral.state.is_open
            ):
                return deferral
        return None

    def grant(
        self,
        deferral: Deferral,
        *,
        precision_furnace: bool = False,
        aerospace: bool = False,
    ) -> Deferral:
        """Check a deferral against the rules and file it."""
        if not deferrable(
            deferral.activity, precision_furnace=precision_furnace, aerospace=aerospace
        ):
            raise StateError(
                f"{deferral.activity.value} cannot be deferred here",
                state="not_deferrable",
            )
        ceiling = maximum_days(deferral.activity)
        if deferral.days > ceiling:
            raise ValidationError(
                f"{deferral.days} days is over the {ceiling} day limit for "
                f"{deferral.activity.value}",
                field="days",
            )
        if not deferral.is_signed:
            raise ValidationError(
                f"a deferral over {SECOND_SIGNATURE_OVER} days needs a countersignature",
                field="countersigned_by",
            )
        if self.open_for(deferral.activity, deferral.subject) is not None:
            raise ConflictError(
                "open deferral", f"{deferral.activity.value} {deferral.subject}"
            )
        self.deferrals.append(deferral)
        return deferral

    def close(self, activity: Activity, subject: str, *, used: bool) -> Deferral:
        current = self.open_for(activity, subject)
        if current is None:
            raise StateError("there is no open deferral to close", state="none")
        index = self.deferrals.index(current)
        state = DeferralState.USED if used else DeferralState.CANCELLED
        closed = Deferral(
            current.activity,
            current.subject,
            current.original_due,
            current.days,
            current.approved_by,
            current.approved_on,
            current.reason,
            current.countersigned_by,
            state,
        )
        self.deferrals[index] = closed
        return closed

    def effective_due(self, activity: Activity, subject: str, due: date) -> date:
        """The due date after any open deferral is taken into account."""
        current = self.open_for(activity, subject)
        if current is None or current.original_due != due:
            return due
        return current.new_due

    def open_deferrals(self) -> list[Deferral]:
        return [d for d in self.deferrals if d.state.is_open]

    def __len__(self) -> int:
        return len(self.deferrals)
