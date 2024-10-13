"""The steps a thermal cycle is made of.

A cycle sheet is a short ordered list and every line on it is one of five kinds
of instruction. The kinds are not decoration: they decide what the step is even
allowed to say, and they decide what a trace has to prove afterwards.

``RAMP``
    get from wherever you are to a set point. Judged on rate, not on time.

``SOAK``
    hold at a set point inside a band for at least a stated time. This is the
    only kind with a minimum time at temperature, and it is the only kind whose
    band gets graded scan by scan.

``QUENCH``
    leave the furnace and get into the medium inside a stated delay. Judged on
    the delay and on the medium, not on a set point at all.

``TEMPER``
    a soak with a different name and one extra rule, that it cannot come before
    a quench in the same cycle.

``HOLD``
    wait, with no temperature promise. Used for load equalisation and for
    waiting on a quench tank. Grades nothing.

The distinction that catches people is between a soak's **minimum time** and a
ramp's **rate**. A ramp that is written with a time is a soak with the band left
off, and a soak that is written with a rate is a ramp somebody is hoping will
count as time at temperature. Both are refused here.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..temperature import Scale, Temperature, TemperatureDelta
from ..timespan import Duration
from ..tolerance import Band


class StepKind(Enum):
    RAMP = "ramp"
    SOAK = "soak"
    QUENCH = "quench"
    TEMPER = "temper"
    HOLD = "hold"

    @property
    def needs_setpoint(self) -> bool:
        return self in {StepKind.RAMP, StepKind.SOAK, StepKind.TEMPER}

    @property
    def is_graded_soak(self) -> bool:
        return self in {StepKind.SOAK, StepKind.TEMPER}

    @property
    def is_in_furnace(self) -> bool:
        return self is not StepKind.QUENCH


@dataclass(frozen=True)
class RampLimit:
    """A rate limit on a ramp, in degrees Fahrenheit per hour."""

    maximum: float | None = None
    minimum: float | None = None

    def __post_init__(self) -> None:
        if self.maximum is not None and self.maximum <= 0:
            raise ValidationError("a maximum rate must be positive", field="maximum")
        if self.minimum is not None and self.minimum <= 0:
            raise ValidationError("a minimum rate must be positive", field="minimum")
        crossed = (
            self.maximum is not None
            and self.minimum is not None
            and self.minimum > self.maximum
        )
        if crossed:
            raise ValidationError("the rate limits cross", field="rate")

    @property
    def is_unlimited(self) -> bool:
        return self.maximum is None and self.minimum is None

    def allows(self, rate_per_hour: float) -> bool:
        magnitude = abs(rate_per_hour)
        if self.maximum is not None and magnitude > self.maximum + 1e-9:
            return False
        return not (self.minimum is not None and magnitude < self.minimum - 1e-9)


@dataclass(frozen=True)
class Step:
    """One line of a cycle sheet."""

    kind: StepKind
    name: str
    setpoint: Temperature | None = None
    tolerance: TemperatureDelta | None = None
    minimum_time: Duration | None = None
    maximum_time: Duration | None = None
    ramp: RampLimit | None = None
    quench_delay: Duration | None = None
    medium: str = ""

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a step needs a name", field="name")
        if self.kind.needs_setpoint and self.setpoint is None:
            raise ValidationError(
                f"a {self.kind.value} step needs a set point", field="setpoint"
            )
        if not self.kind.needs_setpoint and self.setpoint is not None:
            raise ValidationError(
                f"a {self.kind.value} step cannot carry a set point", field="setpoint"
            )
        if self.kind.is_graded_soak:
            if self.tolerance is None:
                raise ValidationError("a soak needs a band", field="tolerance")
            if self.minimum_time is None or not self.minimum_time:
                raise ValidationError("a soak needs a minimum time", field="minimum_time")
            if self.ramp is not None:
                raise ValidationError("a soak cannot carry a ramp rate", field="ramp")
        if self.kind is StepKind.RAMP and self.minimum_time is not None:
            raise ValidationError(
                "a ramp is judged on rate, give it a rate not a time", field="minimum_time"
            )
        if self.kind is StepKind.QUENCH:
            if self.quench_delay is None:
                raise ValidationError("a quench needs a transfer delay", field="quench_delay")
            if not self.medium.strip():
                raise ValidationError("a quench needs a medium", field="medium")
        if self.kind is not StepKind.QUENCH and self.quench_delay is not None:
            raise ValidationError(
                "only a quench step carries a transfer delay", field="quench_delay"
            )
        crossed_times = (
            self.maximum_time is not None
            and self.minimum_time is not None
            and self.maximum_time.seconds < self.minimum_time.seconds
        )
        if crossed_times:
            raise ValidationError("the time limits cross", field="maximum_time")

    @property
    def band(self) -> Band | None:
        if self.setpoint is None or self.tolerance is None:
            return None
        return Band.symmetric(self.setpoint, self.tolerance)

    @property
    def grades_temperature(self) -> bool:
        return self.band is not None and self.kind.is_graded_soak

    def rate_limit(self) -> RampLimit:
        return self.ramp if self.ramp is not None else RampLimit()

    def __str__(self) -> str:
        if self.setpoint is not None:
            return f"{self.kind.value} {self.name} at {self.setpoint.format()}"
        return f"{self.kind.value} {self.name}"


def soak(
    name: str,
    setpoint: Temperature,
    tolerance: TemperatureDelta,
    minimum_time: Duration,
    *,
    maximum_time: Duration | None = None,
) -> Step:
    return Step(
        StepKind.SOAK,
        name,
        setpoint=setpoint,
        tolerance=tolerance,
        minimum_time=minimum_time,
        maximum_time=maximum_time,
    )


def ramp(
    name: str,
    setpoint: Temperature,
    *,
    maximum_per_hour: float | None = None,
    minimum_per_hour: float | None = None,
) -> Step:
    return Step(
        StepKind.RAMP,
        name,
        setpoint=setpoint,
        ramp=RampLimit(maximum_per_hour, minimum_per_hour),
    )


def quench(name: str, medium: str, delay: Duration) -> Step:
    return Step(StepKind.QUENCH, name, quench_delay=delay, medium=medium)


def temper(
    name: str, setpoint: Temperature, tolerance: TemperatureDelta, minimum_time: Duration
) -> Step:
    return Step(
        StepKind.TEMPER,
        name,
        setpoint=setpoint,
        tolerance=tolerance,
        minimum_time=minimum_time,
    )


def hold(name: str, minimum_time: Duration | None = None) -> Step:
    return Step(StepKind.HOLD, name, minimum_time=minimum_time)


DEFAULT_SOAK_TOLERANCE = TemperatureDelta(25.0, Scale.FAHRENHEIT)
