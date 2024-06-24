"""Furnace class, instrumentation type, and the intervals they decide together.

Two independent gradings sit on every furnace and they measure different things.

**Furnace class** is how tight the furnace holds temperature across its working
volume. Class 1 is plus or minus five degrees and is a vacuum furnace somebody
paid a lot of money for. Class 6 is plus or minus fifty and is a big gas fired
box for normalising. The class is a promise about uniformity and nothing else.

**Instrumentation type** is how well the furnace is watched. Type A carries a
recording controller, load sensors and an independent over temperature circuit.
Type E is a controller with a dial on it. The type is a promise about
observation and nothing else.

The two are independent: a class 1 furnace with type E instrumentation is a
perfectly coherent thing and it is a very badly watched precise furnace.

Where they stop being independent is the **testing interval**. A survey proves
uniformity, and how long that proof stays good depends on how closely the
furnace is watched in between. So the survey interval is a function of both, and
that is the rule people get wrong by looking up one axis and stopping.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..calendar_rules import Interval
from ..errors import ValidationError
from ..temperature import Scale, TemperatureDelta


class FurnaceClass(Enum):
    """How tightly the furnace holds its set point across the work zone."""

    CLASS_1 = 1
    CLASS_2 = 2
    CLASS_3 = 3
    CLASS_4 = 4
    CLASS_5 = 5
    CLASS_6 = 6

    @classmethod
    def parse(cls, text: str) -> FurnaceClass:
        cleaned = text.strip().lower().removeprefix("class").strip()
        try:
            return cls(int(cleaned))
        except ValueError:
            raise ValidationError(f"unknown furnace class {text!r}", field="class") from None

    @property
    def is_precision(self) -> bool:
        return self.value <= 2

    def __str__(self) -> str:
        return f"class {self.value}"


class InstrumentationType(Enum):
    """How closely the furnace is watched."""

    A = "A"
    B = "B"
    C = "C"
    D = "D"
    E = "E"

    @classmethod
    def parse(cls, text: str) -> InstrumentationType:
        cleaned = text.strip().upper().removeprefix("TYPE").strip()
        try:
            return cls(cleaned)
        except ValueError:
            raise ValidationError(
                f"unknown instrumentation type {text!r}", field="instrumentation"
            ) from None

    @property
    def rank(self) -> int:
        """A for best watched down to E. Used only for comparisons."""
        return "ABCDE".index(self.value)

    def at_least(self, other: InstrumentationType) -> bool:
        return self.rank <= other.rank


_TOLERANCE_F: dict[int, float] = {1: 5.0, 2: 10.0, 3: 15.0, 4: 20.0, 5: 25.0, 6: 50.0}


def uniformity_tolerance(furnace_class: FurnaceClass) -> TemperatureDelta:
    """The plus or minus band a survey has to fit inside."""
    return TemperatureDelta(_TOLERANCE_F[furnace_class.value], Scale.FAHRENHEIT)


@dataclass(frozen=True)
class SensorRequirement:
    """What instrumentation of one type has to carry."""

    control_sensors: int
    recording_required: bool
    over_temperature_required: bool
    load_sensors_required: bool

    @property
    def total_permanent_sensors(self) -> int:
        return self.control_sensors + (1 if self.over_temperature_required else 0)


_REQUIREMENTS: dict[str, SensorRequirement] = {
    "A": SensorRequirement(2, True, True, True),
    "B": SensorRequirement(2, True, False, True),
    "C": SensorRequirement(1, True, True, False),
    "D": SensorRequirement(1, True, False, False),
    "E": SensorRequirement(1, False, False, False),
}


def sensor_requirements(instrumentation: InstrumentationType) -> SensorRequirement:
    return _REQUIREMENTS[instrumentation.value]


_SAT_MONTHS: dict[str, int] = {"A": 3, "B": 3, "C": 2, "D": 1, "E": 1}


def sat_interval(instrumentation: InstrumentationType) -> Interval:
    """How often a system accuracy test is due. Instrumentation only."""
    return Interval.months(_SAT_MONTHS[instrumentation.value])


_BASE_TUS_MONTHS: dict[int, int] = {1: 3, 2: 3, 3: 6, 4: 6, 5: 12, 6: 12}


def tus_interval(
    furnace_class: FurnaceClass,
    instrumentation: InstrumentationType,
    *,
    consecutive_passes: int = 0,
) -> Interval:
    """How often a uniformity survey is due.

    The base interval comes from the furnace class. Instrumentation then moves
    it: type A and B earn a doubling, type D and E lose half, and type C sits
    where the class put it. A run of clean surveys earns one further doubling,
    and only one, and only for furnaces watched at type C or better. A badly
    watched furnace does not earn extra rope for behaving.
    """
    if consecutive_passes < 0:
        raise ValidationError(
            "consecutive passes cannot be negative", field="consecutive_passes"
        )
    months = _BASE_TUS_MONTHS[furnace_class.value]
    if instrumentation.at_least(InstrumentationType.B):
        months *= 2
    elif not instrumentation.at_least(InstrumentationType.C):
        months = max(1, months // 2)
    if consecutive_passes >= 3 and instrumentation.at_least(InstrumentationType.C):
        months *= 2
    return Interval.months(months)
