"""Judging a system accuracy test.

The tolerance is not one number. It comes off the furnace class, it is stated as
the greater of a fixed amount and a percentage of the reading, and it moves
again with the shop's correction policy.

That last part is the one worth stating plainly, because it looks backwards
until you say it out loud. A shop that applies its corrections has removed a
known error and may spend the full tolerance on what is left. A shop that does
not apply them is still carrying that error inside the number it just wrote
down, so it has to pass by a wider margin to prove the same thing. Uncorrected
testing gets the **tighter** limit, not the looser one.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass, InstrumentationType
from ..temperature import Scale, Temperature, TemperatureDelta
from .model import SatMethod, SatTest

UNCORRECTED_FACTOR = 0.75


class SatVerdict(Enum):
    PASSED = "passed"
    FAILED = "failed"

    @property
    def is_pass(self) -> bool:
        return self is SatVerdict.PASSED


_FIXED_F: dict[int, float] = {1: 2.0, 2: 2.0, 3: 4.0, 4: 4.0, 5: 5.0, 6: 5.0}
_PERCENT: dict[int, float] = {1: 0.2, 2: 0.2, 3: 0.4, 4: 0.4, 5: 0.5, 6: 0.5}


def sat_tolerance(
    furnace_class: FurnaceClass,
    at: Temperature,
    *,
    apply_corrections: bool = True,
) -> TemperatureDelta:
    """The allowed difference between the system and the test sensor."""
    fixed = _FIXED_F[furnace_class.value]
    percent = _PERCENT[furnace_class.value]
    proportional = abs(at.degf) * percent / 100.0
    magnitude = max(fixed, proportional)
    if not apply_corrections:
        magnitude *= UNCORRECTED_FACTOR
    return TemperatureDelta(magnitude, Scale.FAHRENHEIT)


def method_allowed(method: SatMethod, instrumentation: InstrumentationType) -> bool:
    """The alternate method needs redundant sensors, so type A or B only."""
    if method is SatMethod.PROBE:
        return True
    return instrumentation.at_least(InstrumentationType.B)


@dataclass(frozen=True)
class SatResult:
    """The judged test."""

    test: SatTest
    tolerance: TemperatureDelta
    verdict: SatVerdict
    margin: TemperatureDelta
    notes: tuple[str, ...] = ()

    @property
    def difference(self) -> TemperatureDelta:
        return self.test.difference

    @property
    def is_pass(self) -> bool:
        return self.verdict.is_pass

    @property
    def used_fraction(self) -> float:
        """How much of the allowance the difference consumed, as a fraction."""
        limit = abs(self.tolerance.degf)
        if limit == 0:
            return 0.0
        return abs(self.difference.degf) / limit

    def __str__(self) -> str:
        return (
            f"{self.test.number} {self.verdict.value}: "
            f"{self.difference.format()} against {self.tolerance.format()}"
        )


def evaluate(
    test: SatTest,
    furnace_class: FurnaceClass,
    instrumentation: InstrumentationType,
) -> SatResult:
    """Judge one test against the furnace it was run on."""
    if not method_allowed(test.method, instrumentation):
        raise ValidationError(
            f"the alternate method needs type B instrumentation or better, "
            f"this furnace is type {instrumentation.value}",
            field="method",
        )
    tolerance = sat_tolerance(
        furnace_class, test.setpoint, apply_corrections=test.apply_corrections
    )
    difference = test.difference
    limit = abs(tolerance.degf)
    within = abs(difference.degf) <= limit + 1e-9
    margin = TemperatureDelta(limit - abs(difference.degf), Scale.FAHRENHEIT)
    notes: list[str] = []
    if not test.apply_corrections:
        notes.append("corrections not applied, tightened tolerance")
    if within and abs(difference.degf) > limit * 0.9:
        notes.append("passed on less than a tenth of the allowance")
    return SatResult(
        test,
        tolerance,
        SatVerdict.PASSED if within else SatVerdict.FAILED,
        margin,
        tuple(notes),
    )


def worst_of(results: list[SatResult]) -> SatResult | None:
    """The result that used the most of its allowance."""
    if not results:
        return None
    return max(results, key=lambda r: r.used_fraction)
