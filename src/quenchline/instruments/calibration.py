"""Instrument calibration records, and what a failure costs backwards.

A calibration has two halves and the shop cares about them for opposite reasons.

**As found** is what the instrument read before anybody touched it. It is the
only evidence there is about what the instrument was doing yesterday, last week
and last month, so an as found failure does not just mean "fix it". It means
every load run since the previous calibration was measured by an instrument now
known to be out, and somebody has to go and look at them.

**As left** is what it read after adjustment. It governs the future only. An
instrument that cannot be brought inside tolerance as left does not go back on a
furnace whatever its history.

The pairing produces three outcomes and they are not a severity scale. ADJUSTED
is the awkward one: the instrument is fine to use tomorrow and there is a pile
of paperwork to redo from last quarter.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import Enum

from ..calendar_rules import DueRule, Interval, due_date
from ..errors import ValidationError
from ..identity import InstrumentTag
from ..temperature import Scale, Temperature, TemperatureDelta


class CalibrationVerdict(Enum):
    """The outcome of one calibration."""

    PASSED = "passed"
    ADJUSTED = "adjusted"
    FAILED = "failed"

    @property
    def is_usable(self) -> bool:
        """Whether the instrument may be used after this calibration."""
        return self is not CalibrationVerdict.FAILED

    @property
    def invalidates_history(self) -> bool:
        """Whether work done before this calibration is now suspect."""
        return self is not CalibrationVerdict.PASSED


@dataclass(frozen=True)
class CalibrationCheck:
    """One nominal point, read before and after adjustment."""

    nominal: Temperature
    as_found: Temperature
    as_left: Temperature | None = None

    @property
    def found_error(self) -> TemperatureDelta:
        return TemperatureDelta(self.as_found.degf - self.nominal.degf, Scale.FAHRENHEIT)

    @property
    def left_error(self) -> TemperatureDelta | None:
        if self.as_left is None:
            return None
        return TemperatureDelta(self.as_left.degf - self.nominal.degf, Scale.FAHRENHEIT)

    @property
    def was_adjusted(self) -> bool:
        if self.as_left is None:
            return False
        return abs(self.as_left.degf - self.as_found.degf) > 1e-9


@dataclass(frozen=True)
class InstrumentCalibration:
    """One calibration event for one instrument."""

    number: str
    instrument: InstrumentTag
    performed: date
    checks: tuple[CalibrationCheck, ...]
    tolerance: TemperatureDelta
    technician: str = ""
    standard: str = ""

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("calibration number is blank", field="number")
        if not self.checks:
            raise ValidationError("a calibration needs at least one point", field="checks")
        if self.tolerance.degf <= 0:
            raise ValidationError("tolerance must be positive", field="tolerance")

    @property
    def worst_found(self) -> CalibrationCheck:
        return max(self.checks, key=lambda c: abs(c.found_error.degf))

    @property
    def worst_left(self) -> CalibrationCheck | None:
        worst: CalibrationCheck | None = None
        largest = -1.0
        for check in self.checks:
            error = check.left_error
            if error is None:
                continue
            if abs(error.degf) > largest:
                largest = abs(error.degf)
                worst = check
        return worst

    def as_found_passed(self) -> bool:
        limit = abs(self.tolerance.degf) + 1e-9
        return all(abs(c.found_error.degf) <= limit for c in self.checks)

    def as_left_passed(self) -> bool:
        """True when every point that has an as left reading is inside tolerance.

        A point with no as left reading was not adjusted, so its as found
        reading stands as its as left reading.
        """
        limit = abs(self.tolerance.degf) + 1e-9
        for check in self.checks:
            error = check.left_error or check.found_error
            if abs(error.degf) > limit:
                return False
        return True

    @property
    def verdict(self) -> CalibrationVerdict:
        if not self.as_left_passed():
            return CalibrationVerdict.FAILED
        if not self.as_found_passed():
            return CalibrationVerdict.ADJUSTED
        if any(c.was_adjusted for c in self.checks):
            return CalibrationVerdict.ADJUSTED
        return CalibrationVerdict.PASSED

    def next_due(
        self,
        interval: Interval,
        rule: DueRule = DueRule.ANNIVERSARY,
    ) -> date:
        return due_date(self.performed, interval, rule)


def suspect_window(
    calibration: InstrumentCalibration,
    previous: InstrumentCalibration | None,
) -> tuple[date, date] | None:
    """The dates whose work this calibration throws into doubt.

    ``None`` when the instrument passed as found, because nothing is in doubt.
    With no previous calibration on file the window opens at the instrument's
    own calibration date, which is the most that can honestly be claimed.
    """
    if not calibration.verdict.invalidates_history:
        return None
    start = calibration.performed if previous is None else previous.performed
    return (start, calibration.performed)


def error_at(
    calibration: InstrumentCalibration, nominal: Temperature
) -> TemperatureDelta | None:
    """The as found error at one nominal point, if that point was checked."""
    for check in calibration.checks:
        if abs(check.nominal.degf - nominal.degf) < 1e-9:
            return check.found_error
    return None
