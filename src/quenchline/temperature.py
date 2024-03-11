"""Temperature values, deltas and tolerance bands.

The shop works in degrees Fahrenheit on the floor and in degrees Celsius on
anything that came from a European customer, so a temperature is never a bare
float in this codebase. It carries its scale.

Two things get confused constantly and are kept apart here on purpose:

``Temperature``
    a point on a scale. 1550 degF is a temperature.

``TemperatureDelta``
    a difference. A plus or minus 10 degree tolerance is a delta, and converting
    a delta between scales uses the ratio only, never the offset.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from .errors import OutOfRangeError, ParseError, ValidationError

ABSOLUTE_ZERO_C: Final = -273.15
ABSOLUTE_ZERO_F: Final = -459.67
F_PER_C: Final = 1.8


class Scale(Enum):
    """A temperature scale."""

    FAHRENHEIT = "F"
    CELSIUS = "C"

    @property
    def symbol(self) -> str:
        return self.value

    @classmethod
    def parse(cls, text: str) -> Scale:
        cleaned = text.strip().upper().lstrip("°")
        if cleaned in {"F", "DEGF", "FAHRENHEIT"}:
            return cls.FAHRENHEIT
        if cleaned in {"C", "DEGC", "CELSIUS", "CENTIGRADE"}:
            return cls.CELSIUS
        raise ParseError("not a temperature scale", text=text, field="scale")


_VALUE_RE: Final = re.compile(
    r"^\s*(?P<value>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?:°\s*)?(?P<scale>[A-Za-z]+)\s*$"
)


@dataclass(frozen=True, order=False)
class TemperatureDelta:
    """A difference between two temperatures, on a named scale."""

    magnitude: float
    scale: Scale

    def to(self, scale: Scale) -> TemperatureDelta:
        if scale is self.scale:
            return self
        if scale is Scale.CELSIUS:
            return TemperatureDelta(self.magnitude / F_PER_C, Scale.CELSIUS)
        return TemperatureDelta(self.magnitude * F_PER_C, Scale.FAHRENHEIT)

    @property
    def degf(self) -> float:
        return self.to(Scale.FAHRENHEIT).magnitude

    @property
    def degc(self) -> float:
        return self.to(Scale.CELSIUS).magnitude

    def __abs__(self) -> TemperatureDelta:
        return TemperatureDelta(abs(self.magnitude), self.scale)

    def __neg__(self) -> TemperatureDelta:
        return TemperatureDelta(-self.magnitude, self.scale)

    def __add__(self, other: TemperatureDelta) -> TemperatureDelta:
        return TemperatureDelta(self.magnitude + other.to(self.scale).magnitude, self.scale)

    def __sub__(self, other: TemperatureDelta) -> TemperatureDelta:
        return TemperatureDelta(self.magnitude - other.to(self.scale).magnitude, self.scale)

    def __mul__(self, factor: float) -> TemperatureDelta:
        return TemperatureDelta(self.magnitude * factor, self.scale)

    def __lt__(self, other: TemperatureDelta) -> bool:
        return self.degf < other.degf

    def __le__(self, other: TemperatureDelta) -> bool:
        return self.degf <= other.degf

    def __gt__(self, other: TemperatureDelta) -> bool:
        return self.degf > other.degf

    def __ge__(self, other: TemperatureDelta) -> bool:
        return self.degf >= other.degf

    def format(self, places: int = 1) -> str:
        sign = "+" if self.magnitude >= 0 else "-"
        return f"{sign}{abs(self.magnitude):.{places}f} {self.scale.symbol}"

    def __str__(self) -> str:
        return self.format()


def degf(magnitude: float) -> TemperatureDelta:
    """A delta of ``magnitude`` Fahrenheit degrees."""
    return TemperatureDelta(magnitude, Scale.FAHRENHEIT)


def degc(magnitude: float) -> TemperatureDelta:
    """A delta of ``magnitude`` Celsius degrees."""
    return TemperatureDelta(magnitude, Scale.CELSIUS)


@dataclass(frozen=True, order=False)
class Temperature:
    """A point on a temperature scale."""

    value: float
    scale: Scale

    def __post_init__(self) -> None:
        floor = ABSOLUTE_ZERO_F if self.scale is Scale.FAHRENHEIT else ABSOLUTE_ZERO_C
        if self.value < floor - 1e-9:
            raise OutOfRangeError(
                "below absolute zero",
                value=self.value,
                low=floor,
                field="temperature",
            )

    @classmethod
    def fahrenheit(cls, value: float) -> Temperature:
        return cls(value, Scale.FAHRENHEIT)

    @classmethod
    def celsius(cls, value: float) -> Temperature:
        return cls(value, Scale.CELSIUS)

    @classmethod
    def parse(cls, text: str, *, default_scale: Scale | None = None) -> Temperature:
        """Read ``1550F``, ``845 C``, ``1550 degF`` or a bare number.

        A bare number is only accepted when ``default_scale`` is given, because
        guessing the scale of a naked 850 is how a job gets run 300 degrees cold.
        """
        stripped = text.strip()
        if not stripped:
            raise ParseError("empty temperature", text=text, field="temperature")
        match = _VALUE_RE.match(stripped)
        if match is None:
            try:
                bare = float(stripped)
            except ValueError:
                raise ParseError("not a temperature", text=text, field="temperature") from None
            if default_scale is None:
                raise ParseError(
                    "temperature has no scale and no default was given",
                    text=text,
                    field="temperature",
                )
            return cls(bare, default_scale)
        return cls(float(match.group("value")), Scale.parse(match.group("scale")))

    def to(self, scale: Scale) -> Temperature:
        if scale is self.scale:
            return self
        if scale is Scale.CELSIUS:
            return Temperature((self.value - 32.0) / F_PER_C, Scale.CELSIUS)
        return Temperature(self.value * F_PER_C + 32.0, Scale.FAHRENHEIT)

    @property
    def degf(self) -> float:
        return self.to(Scale.FAHRENHEIT).value

    @property
    def degc(self) -> float:
        return self.to(Scale.CELSIUS).value

    def __add__(self, delta: TemperatureDelta) -> Temperature:
        return Temperature(self.value + delta.to(self.scale).magnitude, self.scale)

    def __sub__(self, other: Temperature | TemperatureDelta) -> Temperature | TemperatureDelta:
        if isinstance(other, TemperatureDelta):
            return Temperature(self.value - other.to(self.scale).magnitude, self.scale)
        return TemperatureDelta(self.value - other.to(self.scale).value, self.scale)

    def difference(self, other: Temperature) -> TemperatureDelta:
        """The signed difference ``self - other`` expressed on ``self``'s scale."""
        return TemperatureDelta(self.value - other.to(self.scale).value, self.scale)

    def __lt__(self, other: Temperature) -> bool:
        return self.degf < other.degf

    def __le__(self, other: Temperature) -> bool:
        return self.degf <= other.degf

    def __gt__(self, other: Temperature) -> bool:
        return self.degf > other.degf

    def __ge__(self, other: Temperature) -> bool:
        return self.degf >= other.degf

    def close_to(self, other: Temperature, tolerance: TemperatureDelta) -> bool:
        return abs(self.degf - other.degf) <= abs(tolerance.degf) + 1e-9

    def format(self, places: int = 0) -> str:
        return f"{self.value:.{places}f} {self.scale.symbol}"

    def __str__(self) -> str:
        return self.format()


def coerce_scale(values: list[Temperature]) -> Scale:
    """The scale a list of temperatures should be reported on.

    Mixed input is legal, and the answer is the scale most of them already use.
    A tie goes to Fahrenheit, which is what the floor paperwork uses.
    """
    if not values:
        raise ValidationError("no temperatures to coerce", field="values")
    fahrenheit = sum(1 for v in values if v.scale is Scale.FAHRENHEIT)
    return Scale.FAHRENHEIT if fahrenheit * 2 >= len(values) else Scale.CELSIUS
