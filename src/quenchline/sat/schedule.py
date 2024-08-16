"""The system accuracy test history for a furnace, and what is due when.

A SAT is only worth anything as part of a run. One passing test proves the
system was honest on one afternoon. The register keeps the whole sequence,
because three things fall out of the sequence and none of them out of a single
test:

* **when the next one is due**, which the instrumentation type sets and a run of
  clean tests can stretch;
* **what a failure reaches back to**, which is every load run since the last
  passing test, not since the last test;
* **whether the furnace may run at all today**, which needs a passing test that
  has not expired.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..calendar_rules import DueRule, Interval, days_until, is_overdue
from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass, InstrumentationType, sat_interval
from ..identity import FurnaceTag
from .evaluate import SatResult, evaluate
from .model import SatTest

EXTENSION_AFTER_PASSES = 4
MAX_EXTENSION_MONTHS = 6


@dataclass(frozen=True)
class SatDue:
    """When the next test is due on one furnace."""

    furnace: FurnaceTag
    last_passed: date | None
    due: date | None
    days_left: int | None
    overdue: bool
    interval: Interval

    @property
    def never_tested(self) -> bool:
        return self.last_passed is None


@dataclass
class SatHistory:
    """Every system accuracy test on one furnace, oldest first."""

    furnace: FurnaceTag
    furnace_class: FurnaceClass
    instrumentation: InstrumentationType
    results: list[SatResult] = field(default_factory=list)

    def file(self, test: SatTest) -> SatResult:
        """Judge a test and add it to the history."""
        if str(test.furnace) != str(self.furnace):
            raise ValidationError(
                f"test {test.number} belongs to {test.furnace}", field="furnace"
            )
        if any(r.test.number == test.number for r in self.results):
            raise ValidationError(f"test {test.number} is already on file", field="number")
        result = evaluate(test, self.furnace_class, self.instrumentation)
        self.results.append(result)
        self.results.sort(key=lambda r: r.test.performed)
        return result

    @property
    def is_empty(self) -> bool:
        return not self.results

    def latest(self) -> SatResult | None:
        return self.results[-1] if self.results else None

    def latest_pass(self) -> SatResult | None:
        passes = [r for r in self.results if r.is_pass]
        return passes[-1] if passes else None

    def consecutive_passes(self) -> int:
        """Clean tests since the last failure."""
        run = 0
        for result in reversed(self.results):
            if not result.is_pass:
                break
            run += 1
        return run

    def interval(self) -> Interval:
        """The current test interval, including any extension it has earned.

        The extension is capped, because a furnace that has behaved for two
        years is still a furnace and the point of a SAT is to catch the day it
        stops behaving.
        """
        base = sat_interval(self.instrumentation)
        if self.consecutive_passes() < EXTENSION_AFTER_PASSES:
            return base
        stretched = min(base.count * 2, MAX_EXTENSION_MONTHS)
        return Interval.months(stretched)

    def due(self, on: date, *, rule: DueRule = DueRule.ANNIVERSARY, grace: int = 0) -> SatDue:
        latest = self.latest_pass()
        interval = self.interval()
        if latest is None:
            return SatDue(self.furnace, None, None, None, True, interval)
        performed = latest.test.performed
        due_on = interval.after(performed)
        if rule is DueRule.END_OF_MONTH:
            due_on = date(due_on.year, due_on.month, 1)
            due_on = Interval.months(1).after(due_on)
            due_on = date(due_on.year, due_on.month, 1)
        return SatDue(
            self.furnace,
            performed,
            due_on,
            days_until(due_on, on),
            is_overdue(due_on, on, grace=grace),
            interval,
        )

    def in_date(self, on: date, *, grace: int = 0) -> bool:
        """Whether the furnace has a live passing test today."""
        latest = self.latest()
        if latest is not None and not latest.is_pass:
            return False
        return not self.due(on, grace=grace).overdue

    def failure_window(self, failure: SatResult) -> tuple[date, date] | None:
        """The dates a failed test throws into doubt.

        Back to the previous **passing** test, because the tests in between were
        failures too and prove nothing. With no earlier pass the window opens on
        the failure itself, which is the most that can honestly be claimed.
        """
        if failure.is_pass:
            return None
        earlier = [
            r for r in self.results if r.is_pass and r.test.performed < failure.test.performed
        ]
        start = earlier[-1].test.performed if earlier else failure.test.performed
        return (start, failure.test.performed)

    def open_failures(self) -> list[SatResult]:
        """Failures with no passing test after them."""
        out: list[SatResult] = []
        for result in reversed(self.results):
            if result.is_pass:
                break
            out.append(result)
        return list(reversed(out))
