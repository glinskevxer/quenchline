"""Work zones, survey sensor counts and the qualified operating range.

A furnace is not uniform everywhere inside it. The **work zone** is the part the
shop promises is uniform, and it is smaller than the chamber, sometimes much
smaller. Everything about surveys is stated over the work zone and not over the
furnace.

How many sensors a survey needs comes off the zone volume in steps, not
smoothly, and the steps are wide. Anything up to three cubic feet takes five
sensors. From there to two hundred and twenty five takes nine. Past that it is
nine plus one for every further hundred and twenty five cubic feet, and it stops
at forty however big the furnace is.

The **qualified operating range** is the band of temperatures the furnace is
allowed to run at, and it is earned rather than declared. A survey at 1200 and a
survey at 1700 qualify the furnace from 1200 to 1700 and not one degree either
side, because nobody has evidence about 1750.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..errors import ValidationError
from ..measure import Volume
from ..temperature import Temperature
from .classes import FurnaceClass

SMALL_ZONE_CUFT = 3.0
LARGE_ZONE_CUFT = 225.0
EXTRA_SENSOR_PER_CUFT = 125.0
MAX_SENSORS = 40


@dataclass(frozen=True)
class WorkZone:
    """The part of a furnace the shop puts work in."""

    name: str
    volume: Volume
    low: Temperature
    high: Temperature

    def __post_init__(self) -> None:
        if not self.name.strip():
            raise ValidationError("a work zone needs a name", field="name")
        if self.volume.cubic_feet <= 0:
            raise ValidationError("a work zone needs a volume", field="volume")
        if self.high.degf <= self.low.degf:
            raise ValidationError("the zone range must run upward", field="range")

    @property
    def is_small(self) -> bool:
        return self.volume.cubic_feet <= SMALL_ZONE_CUFT

    def covers(self, at: Temperature) -> bool:
        return self.low.degf <= at.degf <= self.high.degf

    def __str__(self) -> str:
        return f"{self.name} ({self.volume})"


def base_sensor_count(volume: Volume) -> int:
    """Sensors required by volume alone, before any class adjustment."""
    cubic_feet = volume.cubic_feet
    if cubic_feet <= 0:
        raise ValidationError("volume must be positive", field="volume")
    if cubic_feet <= SMALL_ZONE_CUFT:
        return 5
    if cubic_feet <= LARGE_ZONE_CUFT:
        return 9
    over = cubic_feet - LARGE_ZONE_CUFT
    extra = int((over + EXTRA_SENSOR_PER_CUFT - 1e-9) // EXTRA_SENSOR_PER_CUFT)
    return min(MAX_SENSORS, 9 + extra)


def survey_sensor_count(volume: Volume, furnace_class: FurnaceClass) -> int:
    """Sensors a uniformity survey needs.

    A precision furnace carries two more than its volume alone would ask for,
    because a five degree band is not something five thermocouples can honestly
    demonstrate across a real work zone. The forty sensor ceiling still applies
    after the addition.
    """
    count = base_sensor_count(volume)
    if furnace_class.is_precision:
        count += 2
    return min(MAX_SENSORS, count)


@dataclass(frozen=True)
class QualifiedRange:
    """The temperatures a furnace has evidence for."""

    low: Temperature
    high: Temperature

    def __post_init__(self) -> None:
        if self.high.degf < self.low.degf:
            raise ValidationError("a qualified range must run upward", field="range")

    @classmethod
    def single(cls, at: Temperature) -> QualifiedRange:
        return cls(at, at)

    @classmethod
    def spanning(cls, points: list[Temperature]) -> QualifiedRange:
        if not points:
            raise ValidationError("no survey points to qualify from", field="points")
        lowest = min(points, key=lambda t: t.degf)
        highest = max(points, key=lambda t: t.degf)
        return cls(lowest, highest)

    @property
    def is_single_point(self) -> bool:
        return abs(self.high.degf - self.low.degf) < 1e-9

    @property
    def width_f(self) -> float:
        return self.high.degf - self.low.degf

    def covers(self, at: Temperature) -> bool:
        return self.low.degf <= at.degf <= self.high.degf

    def extended_to(self, at: Temperature) -> QualifiedRange:
        """Widen the range to include one more surveyed point."""
        low = at if at.degf < self.low.degf else self.low
        high = at if at.degf > self.high.degf else self.high
        return QualifiedRange(low, high)

    def narrowed_to(self, other: QualifiedRange) -> QualifiedRange:
        """The overlap of two ranges, which is what two constraints leave."""
        low = self.low if self.low.degf > other.low.degf else other.low
        high = self.high if self.high.degf < other.high.degf else other.high
        if high.degf < low.degf:
            raise ValidationError("the two ranges do not overlap", field="range")
        return QualifiedRange(low, high)

    def __str__(self) -> str:
        if self.is_single_point:
            return f"{self.low.format()} only"
        return f"{self.low.format()} to {self.high.format()}"
