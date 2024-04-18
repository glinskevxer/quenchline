"""Thermocouple types and their initial tolerance.

A thermocouple is two dissimilar wires joined at one end, and which two wires
they are decides three things this codebase keeps asking about: how hot the
couple can go, how accurate it is when new, and how expensive it is to throw
away. The last one is why the noble metal types get repaired and recalibrated
while a type K expendable gets binned after one run.

The initial tolerance is not a flat number. It is stated as **the greater of a
fixed amount and a percentage of the reading**, so a type K special limits couple
is worth 2.0 degF at 500 degF and 6.2 degF at 1550 degF. Getting that backwards
and using the fixed value everywhere makes every survey at temperature look
better than it is, which is the interesting direction to be wrong in.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import OutOfRangeError, ValidationError
from ..temperature import Scale, Temperature, TemperatureDelta


class JunctionClass(Enum):
    """Base metal or noble metal. The rules differ for almost everything."""

    BASE_METAL = "base"
    NOBLE_METAL = "noble"

    @property
    def is_noble(self) -> bool:
        return self is JunctionClass.NOBLE_METAL


class ToleranceClass(Enum):
    """Standard or special limits of error, as bought."""

    STANDARD = "standard"
    SPECIAL = "special"


@dataclass(frozen=True)
class _TypeSpec:
    positive_leg: str
    negative_leg: str
    junction: JunctionClass
    low_f: float
    high_f: float
    standard_fixed_c: float
    standard_percent: float
    special_fixed_c: float | None
    special_percent: float | None


_SPECS: dict[str, _TypeSpec] = {
    "K": _TypeSpec(
        "nickel chromium",
        "nickel aluminium",
        JunctionClass.BASE_METAL,
        -328.0,
        2282.0,
        2.2,
        0.75,
        1.1,
        0.4,
    ),
    "N": _TypeSpec(
        "nicrosil", "nisil", JunctionClass.BASE_METAL, -328.0, 2372.0, 2.2, 0.75, 1.1, 0.4
    ),
    "J": _TypeSpec(
        "iron", "constantan", JunctionClass.BASE_METAL, 32.0, 1382.0, 2.2, 0.75, 1.1, 0.4
    ),
    "E": _TypeSpec(
        "nickel chromium",
        "constantan",
        JunctionClass.BASE_METAL,
        -328.0,
        1652.0,
        1.7,
        0.5,
        1.0,
        0.4,
    ),
    "T": _TypeSpec(
        "copper", "constantan", JunctionClass.BASE_METAL, -328.0, 662.0, 1.0, 0.75, 0.5, 0.4
    ),
    "R": _TypeSpec(
        "platinum 13 rhodium",
        "platinum",
        JunctionClass.NOBLE_METAL,
        32.0,
        2642.0,
        1.5,
        0.25,
        0.6,
        0.1,
    ),
    "S": _TypeSpec(
        "platinum 10 rhodium",
        "platinum",
        JunctionClass.NOBLE_METAL,
        32.0,
        2642.0,
        1.5,
        0.25,
        0.6,
        0.1,
    ),
    "B": _TypeSpec(
        "platinum 30 rhodium",
        "platinum 6 rhodium",
        JunctionClass.NOBLE_METAL,
        1600.0,
        3092.0,
        0.0,
        0.5,
        None,
        None,
    ),
}


class ThermocoupleType(Enum):
    """The letter designation stamped on the couple."""

    K = "K"
    N = "N"
    J = "J"
    E = "E"
    T = "T"
    R = "R"
    S = "S"
    B = "B"

    @classmethod
    def parse(cls, text: str) -> ThermocoupleType:
        cleaned = text.strip().upper().removeprefix("TYPE").strip()
        try:
            return cls(cleaned)
        except ValueError:
            raise ValidationError(f"unknown thermocouple type {text!r}", field="type") from None

    @property
    def _spec(self) -> _TypeSpec:
        return _SPECS[self.value]

    @property
    def junction(self) -> JunctionClass:
        return self._spec.junction

    @property
    def is_noble(self) -> bool:
        return self._spec.junction.is_noble

    @property
    def legs(self) -> tuple[str, str]:
        return (self._spec.positive_leg, self._spec.negative_leg)

    @property
    def lower_limit(self) -> Temperature:
        return Temperature.fahrenheit(self._spec.low_f)

    @property
    def upper_limit(self) -> Temperature:
        return Temperature.fahrenheit(self._spec.high_f)

    def covers(self, reading: Temperature) -> bool:
        return self._spec.low_f <= reading.degf <= self._spec.high_f

    def has_special_limits(self) -> bool:
        return self._spec.special_fixed_c is not None


def initial_tolerance(
    kind: ThermocoupleType,
    reading: Temperature,
    grade: ToleranceClass = ToleranceClass.STANDARD,
) -> TemperatureDelta:
    """The greater of the fixed limit and the percentage of reading limit.

    The percentage applies to the reading **in Celsius**, which is how the wire
    standards state it, so a Fahrenheit shop that applies the percentage to a
    Fahrenheit number gets an answer that is nearly twice too generous.
    """
    spec = kind._spec
    if not kind.covers(reading):
        raise OutOfRangeError(
            f"type {kind.value} is not rated at this temperature",
            value=reading.degf,
            low=spec.low_f,
            high=spec.high_f,
            field="reading",
        )
    if grade is ToleranceClass.SPECIAL:
        if spec.special_fixed_c is None or spec.special_percent is None:
            raise ValidationError(
                f"type {kind.value} is not made to special limits", field="grade"
            )
        fixed_c = spec.special_fixed_c
        percent = spec.special_percent
    else:
        fixed_c = spec.standard_fixed_c
        percent = spec.standard_percent
    proportional_c = abs(reading.degc) * percent / 100.0
    magnitude_c = max(fixed_c, proportional_c)
    return TemperatureDelta(magnitude_c, Scale.CELSIUS)
