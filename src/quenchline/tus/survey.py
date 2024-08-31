"""The temperature uniformity survey, as a record.

A survey is a rack of thermocouples in the empty work zone, a furnace driven to
a set point, and a recorder writing every couple every thirty seconds until
somebody decides it has settled. It is the most expensive routine thing this
shop does and it is the only evidence that the furnace is what it says it is.

The data shape matters more here than anywhere else in this package:

``SurveyPoint``
    one sensor at one place in the zone. Corner points and the centre point are
    not interchangeable, because the corners are where a furnace fails and a
    survey that lost a corner has lost the thing it was looking for.

``Scan``
    every sensor read at one moment. Readings are stored as complete scans and
    never as one long list per sensor, because a uniformity number is only
    meaningful across sensors read at the same time.

``SurveySetpoint``
    all the scans at one temperature. A survey usually has two or three.

``Survey``
    the whole exercise on one furnace and one work zone.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

from ..errors import NotFoundError, ValidationError
from ..identity import FurnaceTag, InstrumentTag, SensorTag
from ..temperature import Temperature
from ..timespan import Duration


@dataclass(frozen=True)
class SurveyPoint:
    """One sensor at one place in the work zone."""

    sensor: SensorTag
    location: str
    is_corner: bool = False
    is_centre: bool = False

    def __post_init__(self) -> None:
        if not self.location.strip():
            raise ValidationError("a survey point needs a location", field="location")
        if self.is_corner and self.is_centre:
            raise ValidationError(
                "a point cannot be both a corner and the centre", field="point"
            )

    @property
    def key(self) -> str:
        return str(self.sensor)

    def __str__(self) -> str:
        return f"{self.sensor} at {self.location}"


@dataclass(frozen=True)
class Scan:
    """Every sensor read at one moment."""

    elapsed: Duration
    values: tuple[tuple[str, Temperature], ...]

    @classmethod
    def of(cls, elapsed: Duration, values: dict[str, Temperature]) -> Scan:
        return cls(elapsed, tuple(sorted(values.items(), key=lambda pair: pair[0])))

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(key for key, _ in self.values)

    def as_mapping(self) -> dict[str, Temperature]:
        return dict(self.values)

    def get(self, key: str) -> Temperature:
        for candidate, value in self.values:
            if candidate == key:
                return value
        raise NotFoundError("survey reading", key)

    def has(self, key: str) -> bool:
        return any(candidate == key for candidate, _ in self.values)

    @property
    def is_empty(self) -> bool:
        return not self.values

    def temperatures(self) -> list[Temperature]:
        return [value for _, value in self.values]

    def restricted_to(self, keys: set[str]) -> Scan:
        """The same scan with only the named sensors kept."""
        return Scan(self.elapsed, tuple(p for p in self.values if p[0] in keys))


@dataclass(frozen=True)
class SurveySetpoint:
    """Every scan taken at one temperature."""

    setpoint: Temperature
    scans: tuple[Scan, ...]

    def __post_init__(self) -> None:
        if not self.scans:
            raise ValidationError("a set point needs at least one scan", field="scans")
        elapsed = [scan.elapsed.seconds for scan in self.scans]
        if elapsed != sorted(elapsed):
            raise ValidationError("scans must be in time order", field="scans")

    @property
    def duration(self) -> Duration:
        return self.scans[-1].elapsed

    @property
    def sensor_keys(self) -> tuple[str, ...]:
        return self.scans[0].keys

    def scans_after(self, elapsed: Duration) -> tuple[Scan, ...]:
        return tuple(s for s in self.scans if s.elapsed.seconds >= elapsed.seconds)

    def series(self, key: str) -> list[tuple[Duration, Temperature]]:
        """One sensor's readings across the whole set point."""
        return [(scan.elapsed, scan.get(key)) for scan in self.scans if scan.has(key)]


@dataclass(frozen=True)
class Survey:
    """One uniformity survey."""

    number: str
    furnace: FurnaceTag
    zone: str
    performed: date
    points: tuple[SurveyPoint, ...]
    setpoints: tuple[SurveySetpoint, ...]
    instrument: InstrumentTag | None = None
    technician: str = ""
    notes: tuple[str, ...] = field(default_factory=tuple)

    def __post_init__(self) -> None:
        if not self.number.strip():
            raise ValidationError("survey number is blank", field="number")
        if not self.points:
            raise ValidationError("a survey needs sensors", field="points")
        if not self.setpoints:
            raise ValidationError("a survey needs at least one set point", field="setpoints")
        keys = [p.key for p in self.points]
        if len(set(keys)) != len(keys):
            raise ValidationError("the same sensor is placed twice", field="points")

    @property
    def sensor_count(self) -> int:
        return len(self.points)

    @property
    def corner_count(self) -> int:
        return sum(1 for p in self.points if p.is_corner)

    @property
    def has_centre(self) -> bool:
        return any(p.is_centre for p in self.points)

    @property
    def keys(self) -> tuple[str, ...]:
        return tuple(p.key for p in self.points)

    def point(self, key: str) -> SurveyPoint:
        for candidate in self.points:
            if candidate.key == key:
                return candidate
        raise NotFoundError("survey point", key)

    def at(self, setpoint: Temperature) -> SurveySetpoint:
        for candidate in self.setpoints:
            if abs(candidate.setpoint.degf - setpoint.degf) < 1e-9:
                return candidate
        raise NotFoundError("survey set point", setpoint.format())

    @property
    def temperatures(self) -> tuple[Temperature, ...]:
        return tuple(s.setpoint for s in self.setpoints)

    def __str__(self) -> str:
        return f"{self.number} on {self.furnace} zone {self.zone}"
