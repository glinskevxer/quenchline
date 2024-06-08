"""What an instrument is, and what that lets it be used for.

An instrument in this shop is anything that turns a thermocouple into a number a
person or a controller acts on. There are five jobs, and an instrument qualifies
for a job on two counts that have to be satisfied at the same time:

**accuracy**, stated as a percentage, of the reading or of full scale. Of
reading is the honest one, and the two are wildly different at the bottom of the
range: 0.1 percent of a 2400 degF span is 2.4 degrees whether you are measuring
2000 degF or 200 degF, while 0.1 percent of reading is 0.2 degrees at 200.

**resolution**, the smallest change the display can show. An instrument accurate
to a quarter of a degree that can only display whole degrees is a whole degree
instrument, and the shop treats it as one.

Field test instruments are the strict case, because everything else in the
pyrometry system is measured against them. An instrument that is not good enough
to be a field test instrument can still run a furnace perfectly well.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..temperature import Scale, Temperature, TemperatureDelta


class InstrumentFunction(Enum):
    """The job an instrument is doing."""

    CONTROLLING = "controlling"
    RECORDING = "recording"
    OVER_TEMPERATURE = "over_temperature"
    MONITORING = "monitoring"
    FIELD_TEST = "field_test"

    @property
    def is_test_equipment(self) -> bool:
        return self is InstrumentFunction.FIELD_TEST

    @property
    def acts_on_the_furnace(self) -> bool:
        return self in {
            InstrumentFunction.CONTROLLING,
            InstrumentFunction.OVER_TEMPERATURE,
        }


class InstrumentClass(Enum):
    """How the maker states the accuracy."""

    PERCENT_OF_READING = "percent_of_reading"
    PERCENT_OF_SPAN = "percent_of_span"


class Readout(Enum):
    """Digital instruments have a stated resolution. Analogue ones are read."""

    DIGITAL = "digital"
    ANALOGUE = "analogue"

    @property
    def is_readable_to_a_tenth(self) -> bool:
        return self is Readout.DIGITAL


@dataclass(frozen=True)
class Accuracy:
    """An instrument's stated accuracy."""

    percent: float
    basis: InstrumentClass
    floor_f: float = 0.0

    def __post_init__(self) -> None:
        if self.percent <= 0:
            raise ValidationError("accuracy percentage must be positive", field="percent")
        if self.floor_f < 0:
            raise ValidationError("accuracy floor cannot be negative", field="floor_f")


@dataclass(frozen=True)
class Span:
    """The instrument's measuring range."""

    low: Temperature
    high: Temperature

    def __post_init__(self) -> None:
        if self.high.degf <= self.low.degf:
            raise ValidationError("span must run upward", field="span")

    @property
    def width_f(self) -> float:
        return self.high.degf - self.low.degf

    def covers(self, reading: Temperature) -> bool:
        return self.low.degf <= reading.degf <= self.high.degf


def accuracy_at(accuracy: Accuracy, span: Span, reading: Temperature) -> TemperatureDelta:
    """The instrument's accuracy expressed in degrees at one temperature."""
    if not span.covers(reading):
        raise ValidationError("reading is outside the instrument span", field="reading")
    if accuracy.basis is InstrumentClass.PERCENT_OF_SPAN:
        magnitude = span.width_f * accuracy.percent / 100.0
    else:
        magnitude = abs(reading.degf) * accuracy.percent / 100.0
    return TemperatureDelta(max(magnitude, accuracy.floor_f), Scale.FAHRENHEIT)


def resolution_limit(function: InstrumentFunction, at: Temperature) -> TemperatureDelta:
    """The coarsest display resolution this job tolerates.

    A tenth of a degree is required of field test equipment up to 1000 degF and
    a whole degree above it, because nothing in the shop resolves a tenth of a
    degree at 1800 and pretending otherwise buys a false sense of precision.
    """
    if function.is_test_equipment:
        return TemperatureDelta(0.1 if at.degf <= 1000.0 else 1.0, Scale.FAHRENHEIT)
    if function.acts_on_the_furnace:
        return TemperatureDelta(1.0, Scale.FAHRENHEIT)
    return TemperatureDelta(2.0, Scale.FAHRENHEIT)


def permitted_functions(
    accuracy: Accuracy,
    span: Span,
    resolution: TemperatureDelta,
    readout: Readout,
    at: Temperature,
) -> frozenset[InstrumentFunction]:
    """Every job this instrument is good enough for at one temperature."""
    allowed: set[InstrumentFunction] = set()
    error = accuracy_at(accuracy, span, at)
    for function in InstrumentFunction:
        if resolution.degf > resolution_limit(function, at).degf + 1e-9:
            continue
        if function.is_test_equipment:
            if readout is not Readout.DIGITAL:
                continue
            if error.degf > 1.0 + 1e-9:
                continue
        elif function.acts_on_the_furnace:
            if error.degf > 4.0 + 1e-9:
                continue
        elif error.degf > 10.0 + 1e-9:
            continue
        allowed.add(function)
    return frozenset(allowed)
