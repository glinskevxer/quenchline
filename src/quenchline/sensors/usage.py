"""How much life a thermocouple has left.

Base metal couples drift with use, so the shop retires them on a count rather
than on a calibration. What the count is depends on three things at once, and
the interaction is the part people get wrong:

* the **construction**, expendable or not;
* the **role** it was used in;
* and the **hottest temperature it has ever seen**, which is a property of the
  whole ledger and not of the run being booked.

That last one is the trap. An expendable couple that ran once at 1250 degF is on
the one use limit for the rest of its life, even if every other run was at 900.
Applying the low temperature limit because *this* run was cool is how a couple
gets used four times when it was allowed one.

Noble metal couples are not counted at all. They are governed by hours at
temperature and by recalibration, because platinum does not wear out the way
chromel does, it just goes out of tolerance and gets sent away.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..errors import ValidationError
from ..temperature import Temperature
from ..timespan import Duration
from .record import Construction, SensorRole
from .types import ThermocoupleType

HOT_THRESHOLD = Temperature.fahrenheit(1200.0)
BASE_HOURS_THRESHOLD = Temperature.fahrenheit(1000.0)
NOBLE_HOURS_THRESHOLD = Temperature.fahrenheit(2000.0)


@dataclass(frozen=True)
class UsageEvent:
    """One run a couple was in."""

    on: date
    peak: Temperature
    at_temperature: Duration
    role: SensorRole
    reference: str = ""

    def __post_init__(self) -> None:
        if not self.at_temperature:
            raise ValidationError("a usage event needs a time at temperature", field="duration")


@dataclass(frozen=True)
class UsageLimit:
    """What a couple in one situation is allowed."""

    max_uses: int | None
    max_hours: float | None
    hours_threshold: Temperature

    def __post_init__(self) -> None:
        if self.max_uses is not None and self.max_uses < 1:
            raise ValidationError(
                "a use limit below one retires it on arrival", field="max_uses"
            )
        if self.max_hours is not None and self.max_hours <= 0:
            raise ValidationError("hours limit must be positive", field="max_hours")

    @property
    def is_unlimited(self) -> bool:
        return self.max_uses is None and self.max_hours is None


@dataclass
class UsageLedger:
    """Every run one couple has been in."""

    events: list[UsageEvent] = field(default_factory=list)

    def record(self, event: UsageEvent) -> None:
        self.events.append(event)

    @property
    def uses(self) -> int:
        return len(self.events)

    @property
    def is_empty(self) -> bool:
        return not self.events

    def hottest(self) -> Temperature | None:
        if not self.events:
            return None
        return max((e.peak for e in self.events), key=lambda t: t.degf)

    def hours_above(self, threshold: Temperature) -> float:
        return sum(e.at_temperature.hours for e in self.events if e.peak.degf >= threshold.degf)

    def last_used(self) -> date | None:
        if not self.events:
            return None
        return max(e.on for e in self.events)

    def uses_in_role(self, role: SensorRole) -> int:
        return sum(1 for e in self.events if e.role is role)


def limit_for(
    kind: ThermocoupleType,
    construction: Construction,
    role: SensorRole,
    hottest: Temperature | None,
) -> UsageLimit:
    """The limit that applies, given everything the couple has already done."""
    if kind.is_noble:
        return UsageLimit(None, 200.0, NOBLE_HOURS_THRESHOLD)
    if role is SensorRole.TEST:
        return UsageLimit(None, 1000.0, BASE_HOURS_THRESHOLD)
    if construction.is_expendable:
        ran_hot = hottest is not None and hottest.degf > HOT_THRESHOLD.degf
        return UsageLimit(1 if ran_hot else 3, None, HOT_THRESHOLD)
    if role.is_permanent:
        return UsageLimit(None, None, BASE_HOURS_THRESHOLD)
    return UsageLimit(90, 270.0, BASE_HOURS_THRESHOLD)


@dataclass(frozen=True)
class LifeAssessment:
    """What is left, and which rule is the binding one."""

    limit: UsageLimit
    uses: int
    hours: float
    uses_remaining: int | None
    hours_remaining: float | None
    exhausted: bool
    reason: str

    @property
    def is_spent(self) -> bool:
        return self.exhausted


def assess(
    kind: ThermocoupleType,
    construction: Construction,
    role: SensorRole,
    ledger: UsageLedger,
) -> LifeAssessment:
    """Measure a ledger against the limit that applies to it."""
    limit = limit_for(kind, construction, role, ledger.hottest())
    uses = ledger.uses
    hours = ledger.hours_above(limit.hours_threshold)
    uses_remaining = None if limit.max_uses is None else limit.max_uses - uses
    hours_remaining = None if limit.max_hours is None else limit.max_hours - hours

    if uses_remaining is not None and uses_remaining <= 0:
        return LifeAssessment(
            limit,
            uses,
            hours,
            uses_remaining,
            hours_remaining,
            True,
            f"used {uses} of {limit.max_uses} allowed",
        )
    if hours_remaining is not None and hours_remaining <= 0:
        return LifeAssessment(
            limit,
            uses,
            hours,
            uses_remaining,
            hours_remaining,
            True,
            f"{hours:.1f} of {limit.max_hours:.0f} allowed hours above "
            f"{limit.hours_threshold.format()}",
        )
    if limit.is_unlimited:
        reason = "no use limit, governed by system accuracy testing"
    elif uses_remaining is not None:
        reason = f"{uses_remaining} use(s) left"
    else:
        reason = f"{hours_remaining:.1f} hour(s) left"
    return LifeAssessment(limit, uses, hours, uses_remaining, hours_remaining, False, reason)
