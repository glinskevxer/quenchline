"""Tolerance bands and the shop's rounding rule.

A recipe never says "hold at 1550". It says "hold at 1550 plus 25 minus 25", and
half the arguments in this trade are about whether a reading that landed exactly
on the limit is in or out. It is in. The band is closed at both ends, and every
comparison in this module goes through :meth:`Band.position` so that answer is
given in exactly one place.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .errors import ValidationError
from .temperature import Scale, Temperature, TemperatureDelta, degf

_EPS = 1e-9


class Position(Enum):
    """Where a reading sits relative to a band."""

    BELOW = "below"
    INSIDE = "inside"
    ABOVE = "above"

    @property
    def is_excursion(self) -> bool:
        return self is not Position.INSIDE


@dataclass(frozen=True)
class Band:
    """A set point with an asymmetric tolerance either side of it.

    ``minus`` and ``plus`` are magnitudes, always non negative. A band written
    "1550 +25 -0" is a one sided band and is perfectly legal.
    """

    setpoint: Temperature
    minus: TemperatureDelta
    plus: TemperatureDelta

    def __post_init__(self) -> None:
        if self.minus.magnitude < -_EPS:
            raise ValidationError(
                "minus tolerance is a magnitude, give it unsigned", field="minus"
            )
        if self.plus.magnitude < -_EPS:
            raise ValidationError(
                "plus tolerance is a magnitude, give it unsigned", field="plus"
            )

    @classmethod
    def symmetric(cls, setpoint: Temperature, tolerance: TemperatureDelta) -> Band:
        magnitude = abs(tolerance)
        return cls(setpoint, magnitude, magnitude)

    @classmethod
    def one_sided_high(cls, setpoint: Temperature, plus: TemperatureDelta) -> Band:
        zero = TemperatureDelta(0.0, setpoint.scale)
        return cls(setpoint, zero, abs(plus))

    @classmethod
    def one_sided_low(cls, setpoint: Temperature, minus: TemperatureDelta) -> Band:
        zero = TemperatureDelta(0.0, setpoint.scale)
        return cls(setpoint, abs(minus), zero)

    @classmethod
    def from_limits(cls, low: Temperature, high: Temperature) -> Band:
        """A band described by its two limits rather than by a set point.

        The set point lands in the middle, which is what a customer means by
        "between 1525 and 1575" even when they never say 1550.
        """
        if high.degf < low.degf:
            raise ValidationError("band limits are the wrong way round", field="limits")
        setpoint = low.midpoint(high)
        half = TemperatureDelta((high.degf - low.degf) / 2.0, Scale.FAHRENHEIT)
        return cls(setpoint, half.to(setpoint.scale), half.to(setpoint.scale))

    @property
    def scale(self) -> Scale:
        return self.setpoint.scale

    @property
    def lower(self) -> Temperature:
        return self.setpoint.minus(self.minus)

    @property
    def upper(self) -> Temperature:
        return self.setpoint + self.plus

    @property
    def width(self) -> TemperatureDelta:
        return self.minus.to(self.scale) + self.plus.to(self.scale)

    @property
    def is_symmetric(self) -> bool:
        return abs(self.minus.degf - self.plus.degf) < _EPS

    def position(self, reading: Temperature) -> Position:
        if reading.degf < self.lower.degf - _EPS:
            return Position.BELOW
        if reading.degf > self.upper.degf + _EPS:
            return Position.ABOVE
        return Position.INSIDE

    def contains(self, reading: Temperature) -> bool:
        return self.position(reading) is Position.INSIDE

    def deviation(self, reading: Temperature) -> TemperatureDelta:
        """Signed distance from the set point, on the band's scale."""
        return reading.difference(self.setpoint).to(self.scale)

    def excursion(self, reading: Temperature) -> TemperatureDelta:
        """How far outside the band a reading is. Zero when it is inside."""
        position = self.position(reading)
        if position is Position.INSIDE:
            return TemperatureDelta(0.0, self.scale)
        if position is Position.BELOW:
            return reading.difference(self.lower).to(self.scale)
        return reading.difference(self.upper).to(self.scale)

    def clamp(self, reading: Temperature) -> Temperature:
        position = self.position(reading)
        if position is Position.BELOW:
            return self.lower
        if position is Position.ABOVE:
            return self.upper
        return reading

    def widen(self, extra: TemperatureDelta) -> Band:
        magnitude = abs(extra)
        return Band(self.setpoint, self.minus + magnitude, self.plus + magnitude)

    def tighten(self, amount: TemperatureDelta) -> Band:
        magnitude = abs(amount)
        minus = self.minus - magnitude
        plus = self.plus - magnitude
        if minus.magnitude < -_EPS or plus.magnitude < -_EPS:
            raise ValidationError("cannot tighten a band past its set point", field="amount")
        return Band(self.setpoint, minus, plus)

    def overlaps(self, other: Band) -> bool:
        return self.lower.degf <= other.upper.degf + _EPS and (
            other.lower.degf <= self.upper.degf + _EPS
        )

    def format(self, places: int = 0) -> str:
        if self.is_symmetric:
            return f"{self.setpoint.format(places)} +/-{abs(self.plus.magnitude):.{places}f}"
        return (
            f"{self.setpoint.format(places)} "
            f"+{abs(self.plus.magnitude):.{places}f} "
            f"-{abs(self.minus.magnitude):.{places}f}"
        )

    def __str__(self) -> str:
        return self.format()


def band_from_spec(setpoint: Temperature, spec: str) -> Band:
    """Read a written tolerance such as ``+/-10``, ``+25/-0`` or ``+0/-15``."""
    text = spec.strip().replace(" ", "")
    if not text:
        raise ValidationError("empty tolerance spec", field="spec")
    if text.startswith(("+/-", "±")):
        magnitude = text[3:] if text.startswith("+/-") else text[1:]
        return Band.symmetric(setpoint, TemperatureDelta(float(magnitude), setpoint.scale))
    plus_part, sep, minus_part = text.partition("/")
    if not sep:
        raise ValidationError("tolerance spec needs both sides", field="spec")
    if not plus_part.startswith("+") or not minus_part.startswith("-"):
        raise ValidationError("tolerance spec must read +x/-y", field="spec")
    plus = TemperatureDelta(float(plus_part[1:]), setpoint.scale)
    minus = TemperatureDelta(float(minus_part[1:]), setpoint.scale)
    return Band(setpoint, minus, plus)


DEFAULT_SOAK_BAND = degf(25)
