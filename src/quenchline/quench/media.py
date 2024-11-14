"""Quench media and the baths they live in.

What has to be true about a quench bath before a load goes into it depends
almost entirely on what is in the bath, and the differences are not small:

* **oil** cares about temperature and agitation. Too cold and it will not move
  heat, too hot and it is near its flash point.
* **polymer** cares about all of that and about **concentration** as well, which
  is the whole point of using it. A polymer bath at the wrong concentration is a
  different quench, not a slightly worse one.
* **molten salt** has a floor: below its melting point it is not a bath.
* **gas** has no agitation and no concentration. It has pressure.

So the checks are not a fixed list with some entries skipped. Which checks
*exist* is a property of the medium.

Load ratio matters everywhere and is the one number people forget. Dropping
three thousand pounds of steel into a bath sized for five hundred raises the
bath temperature through its band before the parts have finished cooling, and
the trace of the bath will show it if anybody looks.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..measure import Mass
from ..temperature import Temperature, TemperatureDelta
from ..tolerance import Band


class MediumKind(Enum):
    OIL = "oil"
    POLYMER = "polymer"
    WATER = "water"
    MOLTEN_SALT = "molten_salt"
    GAS = "gas"

    @property
    def is_liquid(self) -> bool:
        return self is not MediumKind.GAS

    @property
    def has_concentration(self) -> bool:
        return self is MediumKind.POLYMER

    @property
    def needs_agitation(self) -> bool:
        return self.is_liquid

    @property
    def has_a_melting_point(self) -> bool:
        return self is MediumKind.MOLTEN_SALT


class Agitation(Enum):
    """The agitation grades the shop books work to."""

    NONE = 0
    MILD = 1
    MODERATE = 2
    GOOD = 3
    STRONG = 4
    VIOLENT = 5

    @property
    def is_moving(self) -> bool:
        return self is not Agitation.NONE

    def at_least(self, other: Agitation) -> bool:
        return self.value >= other.value


_MAX_POUNDS_PER_GALLON: dict[str, float] = {
    "oil": 1.0,
    "polymer": 1.2,
    "water": 1.5,
    "molten_salt": 0.6,
    "gas": 0.0,
}


@dataclass(frozen=True)
class Medium:
    """A quench medium as bought and specified."""

    name: str
    kind: MediumKind
    operating: Band
    minimum_agitation: Agitation = Agitation.MODERATE
    concentration_low: float | None = None
    concentration_high: float | None = None
    melting_point: Temperature | None = None

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a medium needs a name", field="name")
        if self.kind.has_concentration:
            if self.concentration_low is None or self.concentration_high is None:
                raise ValidationError(
                    "a polymer needs a concentration range", field="concentration"
                )
            if self.concentration_low > self.concentration_high:
                raise ValidationError(
                    "the concentration range is inverted", field="concentration"
                )
        elif self.concentration_low is not None or self.concentration_high is not None:
            raise ValidationError(
                f"a {self.kind.value} bath has no concentration", field="concentration"
            )
        if self.kind.has_a_melting_point and self.melting_point is None:
            raise ValidationError("a salt bath needs a melting point", field="melting_point")
        if not self.kind.needs_agitation and self.minimum_agitation.is_moving:
            raise ValidationError(
                f"a {self.kind.value} quench has no agitation", field="minimum_agitation"
            )

    @property
    def max_pounds_per_gallon(self) -> float:
        return _MAX_POUNDS_PER_GALLON[self.kind.value]

    def concentration_ok(self, percent: float) -> bool:
        if not self.kind.has_concentration:
            raise ValidationError(
                f"a {self.kind.value} bath has no concentration", field="concentration"
            )
        assert self.concentration_low is not None
        assert self.concentration_high is not None
        return self.concentration_low - 1e-9 <= percent <= self.concentration_high + 1e-9

    def above_melting(self, at: Temperature) -> bool:
        if self.melting_point is None:
            return True
        return at.degf >= self.melting_point.degf

    def __str__(self) -> str:
        return f"{self.name} ({self.kind.value})"


def oil(name: str, setpoint: Temperature, tolerance: TemperatureDelta) -> Medium:
    return Medium(name, MediumKind.OIL, Band.symmetric(setpoint, tolerance))


def polymer(
    name: str,
    setpoint: Temperature,
    tolerance: TemperatureDelta,
    low: float,
    high: float,
) -> Medium:
    return Medium(
        name,
        MediumKind.POLYMER,
        Band.symmetric(setpoint, tolerance),
        concentration_low=low,
        concentration_high=high,
    )


def gas(name: str, setpoint: Temperature, tolerance: TemperatureDelta) -> Medium:
    return Medium(
        name,
        MediumKind.GAS,
        Band.symmetric(setpoint, tolerance),
        minimum_agitation=Agitation.NONE,
    )


def salt(
    name: str,
    setpoint: Temperature,
    tolerance: TemperatureDelta,
    melting_point: Temperature,
) -> Medium:
    return Medium(
        name,
        MediumKind.MOLTEN_SALT,
        Band.symmetric(setpoint, tolerance),
        melting_point=melting_point,
    )


def load_ratio(weight: Mass, gallons: float) -> float:
    """Pounds of work per gallon of bath."""
    if gallons <= 0:
        raise ValidationError("a bath needs a volume", field="gallons")
    return weight.pounds_value / gallons
