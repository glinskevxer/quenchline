"""Is this furnace getting worse.

A furnace does not fail a survey out of nowhere. It fails after two years of the
worst corner creeping a degree at a time, and every one of those surveys passed.
The pass or fail verdict is therefore the least useful thing in the survey file,
and the **margin** is the useful one: how much of the band the furnace actually
used.

So a trend here is fitted to the margin over time, not to the verdict, and it
produces one of three answers with a projected crossing date where there is one.

The refusal worth keeping: **two points are not a trend**. A fit through two
surveys will always produce a slope and it means nothing. Three is the minimum,
and even three is stated as a direction rather than as a date unless the fit is
consistent.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from enum import Enum

from ..errors import ValidationError
from ..numeric import mean, slope
from ..temperature import Scale, TemperatureDelta

MINIMUM_POINTS = 3
DAYS_PER_YEAR = 365.25
FLAT_PER_YEAR = 0.25


class Direction(Enum):
    IMPROVING = "improving"
    STEADY = "steady"
    WORSENING = "worsening"

    @property
    def needs_watching(self) -> bool:
        return self is Direction.WORSENING


@dataclass(frozen=True)
class SurveyPoint:
    """One survey reduced to the day it ran and how much band it used."""

    on: date
    used: TemperatureDelta
    band: TemperatureDelta

    def __post_init__(self) -> None:
        if self.band.degf <= 0:
            raise ValidationError("the band must be positive", field="band")

    @property
    def fraction(self) -> float:
        return abs(self.used.degf) / abs(self.band.degf)


@dataclass(frozen=True)
class Trend:
    """What a run of surveys says about where a furnace is going."""

    points: tuple[SurveyPoint, ...]
    direction: Direction
    per_year: float
    average_fraction: float
    crossing: date | None

    @property
    def is_worsening(self) -> bool:
        return self.direction is Direction.WORSENING

    @property
    def latest(self) -> SurveyPoint:
        return self.points[-1]

    def __str__(self) -> str:
        text = (
            f"{self.direction.value}, {self.per_year:+.2f} of the band per year, "
            f"now using {self.latest.fraction:.0%}"
        )
        if self.crossing is not None:
            text += f", out of band around {self.crossing.isoformat()}"
        return text


def trend_of(points: list[SurveyPoint], *, flat_per_year: float = FLAT_PER_YEAR) -> Trend:
    """Fit a trend through the band fraction of a run of surveys."""
    if len(points) < MINIMUM_POINTS:
        raise ValidationError(
            f"a trend needs at least {MINIMUM_POINTS} surveys, this has {len(points)}",
            field="points",
        )
    if flat_per_year <= 0:
        raise ValidationError("the flat threshold must be positive", field="flat_per_year")

    ordered = tuple(sorted(points, key=lambda p: p.on))
    origin = ordered[0].on
    xs = [(p.on - origin).days / DAYS_PER_YEAR for p in ordered]
    ys = [p.fraction for p in ordered]
    if len(set(xs)) < 2:
        raise ValidationError("every survey is on the same day", field="points")

    per_year = slope(xs, ys)
    average = mean(ys)

    if per_year > flat_per_year:
        direction = Direction.WORSENING
    elif per_year < -flat_per_year:
        direction = Direction.IMPROVING
    else:
        direction = Direction.STEADY

    crossing = _crossing(ordered[-1], per_year) if direction is Direction.WORSENING else None
    return Trend(ordered, direction, per_year, average, crossing)


def _crossing(latest: SurveyPoint, per_year: float) -> date | None:
    """When the band fraction is projected to reach one."""
    if per_year <= 0:
        return None
    headroom = 1.0 - latest.fraction
    if headroom <= 0:
        return latest.on
    years = headroom / per_year
    return latest.on + timedelta(days=int(years * DAYS_PER_YEAR))


def point(on: date, used_degf: float, band_degf: float) -> SurveyPoint:
    """Build a point from raw Fahrenheit numbers."""
    return SurveyPoint(
        on,
        TemperatureDelta(used_degf, Scale.FAHRENHEIT),
        TemperatureDelta(band_degf, Scale.FAHRENHEIT),
    )


def worst_first(trends: dict[str, Trend]) -> list[tuple[str, Trend]]:
    """Furnaces ordered by how soon they are in trouble."""

    def key(pair: tuple[str, Trend]) -> tuple[int, float, str]:
        name, trend = pair
        return (0 if trend.is_worsening else 1, -trend.latest.fraction, name)

    return sorted(trends.items(), key=key)
