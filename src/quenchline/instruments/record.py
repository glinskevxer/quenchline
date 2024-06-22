"""The instrument record.

One row per controller, recorder, chart, over temperature cutout and field test
box in the shop, with its calibration history hanging off it.

The record answers one question that the calibration module deliberately does
not: **is this instrument in calibration today**. That is not the same as "did
its last calibration pass". A calibration that passed eighteen months ago on a
six month interval is a pass and is also long dead, and an instrument whose last
calibration was ADJUSTED is in calibration going forward even though it has left
a mess behind it.
"""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import date
from enum import Enum

from ..calendar_rules import DueRule, Interval
from ..errors import StateError, ValidationError
from ..identity import InstrumentTag
from ..temperature import Temperature, TemperatureDelta
from .calibration import CalibrationVerdict, InstrumentCalibration
from .types import (
    Accuracy,
    InstrumentFunction,
    Readout,
    Span,
    accuracy_at,
    permitted_functions,
)


class InstrumentStatus(Enum):
    IN_SERVICE = "in_service"
    OUT_OF_SERVICE = "out_of_service"
    RETIRED = "retired"

    @property
    def is_usable(self) -> bool:
        return self is InstrumentStatus.IN_SERVICE


@dataclass(frozen=True)
class Instrument:
    """One instrument and everything the shop knows about it."""

    tag: InstrumentTag
    function: InstrumentFunction
    span: Span
    accuracy: Accuracy
    resolution: TemperatureDelta
    readout: Readout = Readout.DIGITAL
    interval: Interval = Interval.months(6)
    due_rule: DueRule = DueRule.ANNIVERSARY
    status: InstrumentStatus = InstrumentStatus.IN_SERVICE
    make: str = ""
    model: str = ""
    serial: str = ""
    calibrations: tuple[InstrumentCalibration, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if self.resolution.degf <= 0:
            raise ValidationError("resolution must be positive", field="resolution")
        for cal in self.calibrations:
            if str(cal.instrument) != str(self.tag):
                raise ValidationError(
                    f"calibration {cal.number} belongs to {cal.instrument}",
                    field="calibrations",
                )

    @property
    def history(self) -> tuple[InstrumentCalibration, ...]:
        return tuple(sorted(self.calibrations, key=lambda c: c.performed))

    @property
    def latest(self) -> InstrumentCalibration | None:
        history = self.history
        return history[-1] if history else None

    def previous_to(self, calibration: InstrumentCalibration) -> InstrumentCalibration | None:
        earlier = [c for c in self.history if c.performed < calibration.performed]
        return earlier[-1] if earlier else None

    def with_calibration(self, calibration: InstrumentCalibration) -> Instrument:
        if str(calibration.instrument) != str(self.tag):
            raise ValidationError(
                f"calibration {calibration.number} belongs to {calibration.instrument}",
                field="calibration",
            )
        if any(c.number == calibration.number for c in self.calibrations):
            raise ValidationError(
                f"calibration {calibration.number} is already on file", field="calibration"
            )
        return replace(self, calibrations=(*self.calibrations, calibration))

    def due_on(self) -> date | None:
        latest = self.latest
        if latest is None:
            return None
        return latest.next_due(self.interval, self.due_rule)

    def in_calibration(self, on: date) -> bool:
        """Whether the instrument may be relied on for a reading taken today."""
        latest = self.latest
        if latest is None:
            return False
        if not latest.verdict.is_usable:
            return False
        due = self.due_on()
        return due is not None and on <= due

    def calibration_state(self, on: date) -> str:
        latest = self.latest
        if latest is None:
            return "never calibrated"
        if latest.verdict is CalibrationVerdict.FAILED:
            return f"failed calibration {latest.number}"
        due = self.due_on()
        if due is not None and on > due:
            return f"overdue since {due.isoformat()}"
        return f"in calibration until {due.isoformat()}" if due else "in calibration"

    def qualified_for(self, function: InstrumentFunction, at: Temperature) -> bool:
        """Whether the hardware is good enough, ignoring calibration."""
        return function in permitted_functions(
            self.accuracy, self.span, self.resolution, self.readout, at
        )

    def error_at(self, at: Temperature) -> TemperatureDelta:
        return accuracy_at(self.accuracy, self.span, at)

    def take_out_of_service(self, reason: str) -> Instrument:
        if self.status is InstrumentStatus.RETIRED:
            raise StateError("a retired instrument is already gone", state="retired")
        if not reason.strip():
            raise ValidationError("give a reason", field="reason")
        return replace(self, status=InstrumentStatus.OUT_OF_SERVICE)

    def return_to_service(self) -> Instrument:
        if self.status is InstrumentStatus.RETIRED:
            raise StateError("a retired instrument cannot come back", state="retired")
        return replace(self, status=InstrumentStatus.IN_SERVICE)

    def retire(self) -> Instrument:
        return replace(self, status=InstrumentStatus.RETIRED)

    def __str__(self) -> str:
        return f"{self.tag} {self.function.value}"
