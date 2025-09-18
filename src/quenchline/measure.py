"""Mass, length and volume, in the two systems the shop actually gets data in.

Load weights arrive in pounds from the floor and kilograms from a European
customer's paperwork. Work zone volumes decide how many survey sensors a furnace
needs, and that rule is written in cubic feet, so a zone entered in millimetres
has to end up on the same ruler before the count is taken.

Same split as :mod:`quenchline.temperature`: a quantity carries its unit, and the
conversion happens in one place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Final

from .errors import ParseError, ValidationError
from .numeric import require_finite

LB_PER_KG: Final = 2.2046226218487757
MM_PER_INCH: Final = 25.4
CUFT_PER_CUM: Final = 35.31466672148859

_QUANTITY_RE: Final = re.compile(
    r"^\s*(?P<value>[+-]?(?:\d+\.?\d*|\.\d+))\s*(?P<unit>[A-Za-z][A-Za-z0-9^]*)?\s*$"
)


class MassUnit(Enum):
    POUND = "lb"
    KILOGRAM = "kg"

    @classmethod
    def parse(cls, text: str) -> MassUnit:
        cleaned = text.strip().lower()
        if cleaned in {"lb", "lbs", "pound", "pounds", "#"}:
            return cls.POUND
        if cleaned in {"kg", "kilo", "kilos", "kilogram", "kilograms"}:
            return cls.KILOGRAM
        raise ParseError("not a mass unit", text=text, field="unit")


class LengthUnit(Enum):
    INCH = "in"
    MILLIMETRE = "mm"

    @classmethod
    def parse(cls, text: str) -> LengthUnit:
        cleaned = text.strip().lower()
        if cleaned in {"in", "inch", "inches", '"'}:
            return cls.INCH
        if cleaned in {"mm", "millimetre", "millimeter", "millimetres", "millimeters"}:
            return cls.MILLIMETRE
        raise ParseError("not a length unit", text=text, field="unit")


@dataclass(frozen=True, order=False)
class Mass:
    """A weight, held on the unit it was given in."""

    value: float
    unit: MassUnit

    def __post_init__(self) -> None:
        require_finite(self.value, "mass")
        if self.value < 0:
            raise ValidationError("mass cannot be negative", field="mass")

    @classmethod
    def pounds(cls, value: float) -> Mass:
        return cls(value, MassUnit.POUND)

    @classmethod
    def kilograms(cls, value: float) -> Mass:
        return cls(value, MassUnit.KILOGRAM)

    @classmethod
    def parse(cls, text: str, *, default_unit: MassUnit | None = None) -> Mass:
        match = _QUANTITY_RE.match(text)
        if match is None:
            raise ParseError("not a mass", text=text, field="mass")
        unit_text = match.group("unit")
        if unit_text is None:
            if default_unit is None:
                raise ParseError("mass has no unit", text=text, field="mass")
            unit = default_unit
        else:
            unit = MassUnit.parse(unit_text)
        return cls(float(match.group("value")), unit)

    def to(self, unit: MassUnit) -> Mass:
        if unit is self.unit:
            return self
        if unit is MassUnit.KILOGRAM:
            return Mass(self.value / LB_PER_KG, MassUnit.KILOGRAM)
        return Mass(self.value * LB_PER_KG, MassUnit.POUND)

    @property
    def pounds_value(self) -> float:
        return self.to(MassUnit.POUND).value

    def __add__(self, other: Mass) -> Mass:
        return Mass(self.value + other.to(self.unit).value, self.unit)

    def __mul__(self, factor: float) -> Mass:
        return Mass(self.value * factor, self.unit)

    def __lt__(self, other: Mass) -> bool:
        return self.pounds_value < other.pounds_value

    def __le__(self, other: Mass) -> bool:
        return self.pounds_value <= other.pounds_value

    def __gt__(self, other: Mass) -> bool:
        return self.pounds_value > other.pounds_value

    def __ge__(self, other: Mass) -> bool:
        return self.pounds_value >= other.pounds_value

    def __str__(self) -> str:
        return f"{self.value:.1f} {self.unit.value}"


@dataclass(frozen=True, order=False)
class Length:
    value: float
    unit: LengthUnit

    def __post_init__(self) -> None:
        require_finite(self.value, "length")
        if self.value < 0:
            raise ValidationError("length cannot be negative", field="length")

    @classmethod
    def inches(cls, value: float) -> Length:
        return cls(value, LengthUnit.INCH)

    @classmethod
    def millimetres(cls, value: float) -> Length:
        return cls(value, LengthUnit.MILLIMETRE)

    def to(self, unit: LengthUnit) -> Length:
        if unit is self.unit:
            return self
        if unit is LengthUnit.MILLIMETRE:
            return Length(self.value * MM_PER_INCH, LengthUnit.MILLIMETRE)
        return Length(self.value / MM_PER_INCH, LengthUnit.INCH)

    @property
    def inches_value(self) -> float:
        return self.to(LengthUnit.INCH).value

    def __lt__(self, other: Length) -> bool:
        return self.inches_value < other.inches_value

    def __gt__(self, other: Length) -> bool:
        return self.inches_value > other.inches_value

    def __str__(self) -> str:
        return f"{self.value:.2f} {self.unit.value}"


@dataclass(frozen=True, order=False)
class Volume:
    """A work zone volume, always reported in cubic feet."""

    cubic_feet: float

    def __post_init__(self) -> None:
        require_finite(self.cubic_feet, "volume")
        if self.cubic_feet < 0:
            raise ValidationError("volume cannot be negative", field="volume")

    @classmethod
    def from_box(cls, width: Length, height: Length, depth: Length) -> Volume:
        cubic_inches = width.inches_value * height.inches_value * depth.inches_value
        return cls(cubic_inches / 1728.0)

    @classmethod
    def cubic_metres(cls, value: float) -> Volume:
        return cls(value * CUFT_PER_CUM)

    @property
    def cubic_metres_value(self) -> float:
        return self.cubic_feet / CUFT_PER_CUM

    def __lt__(self, other: Volume) -> bool:
        return self.cubic_feet < other.cubic_feet

    def __gt__(self, other: Volume) -> bool:
        return self.cubic_feet > other.cubic_feet

    def __str__(self) -> str:
        return f"{self.cubic_feet:.1f} cuft"
