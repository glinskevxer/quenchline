"""When a survey has settled, and what counts as overshooting.

The survey clock does not start when the furnace is switched on. It starts the
moment the **first** sensor anywhere in the zone reaches the bottom of the band,
and from that moment on nothing is allowed to go over the top of it. That single
rule is what stops a shop from cooking the corners to bring the centre up.

The word people trip over is "first". Not the last, not the control sensor, not
the average. The first sensor to arrive starts the clock for everybody, which
means a fast corner makes the survey harder rather than easier.

The overshoot rule itself is not the same on every furnace. On a precision
furnace it is absolute: one reading over the top and the survey is finished. On
a class 5 or 6 box a brief excursion that pulls back inside the band quickly is
tolerated, because the thing has the thermal mass of a car and nobody is
pretending otherwise. The tolerated window is a shop policy and it is stated,
not assumed.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from ..errors import ValidationError
from ..furnaces.classes import FurnaceClass
from ..temperature import Temperature, TemperatureDelta
from ..timespan import Duration, minutes
from ..tolerance import Band
from .survey import Scan, SurveySetpoint


class OvershootPolicy(Enum):
    """How strictly the top of the band is enforced once the clock starts."""

    STRICT = "strict"
    TOLERATED = "tolerated"

    @property
    def allows_recovery(self) -> bool:
        return self is OvershootPolicy.TOLERATED


DEFAULT_RECOVERY = minutes(2)


def policy_for(furnace_class: FurnaceClass) -> OvershootPolicy:
    """Precision furnaces get no rope at all."""
    if furnace_class.is_precision:
        return OvershootPolicy.STRICT
    return OvershootPolicy.TOLERATED


@dataclass(frozen=True)
class Overshoot:
    """One scan where a sensor went over the top of the band."""

    elapsed: Duration
    sensor: str
    reading: Temperature
    excess: TemperatureDelta


@dataclass(frozen=True)
class Stabilization:
    """What happened between the clock starting and the survey ending."""

    started_at: Duration | None
    first_sensor: str | None
    overshoots: tuple[Overshoot, ...]
    recovered: bool
    soak_time: Duration

    @property
    def started(self) -> bool:
        return self.started_at is not None

    @property
    def clean(self) -> bool:
        return self.started and not self.overshoots


def band_for(setpoint: Temperature, tolerance: TemperatureDelta) -> Band:
    return Band.symmetric(setpoint, tolerance)


def first_arrival(data: SurveySetpoint, band: Band) -> tuple[Duration, str] | None:
    """The scan and sensor that first reached the bottom of the band."""
    for scan in data.scans:
        arrived = [key for key, value in scan.values if value.degf >= band.lower.degf - 1e-9]
        if arrived:
            return (scan.elapsed, sorted(arrived)[0])
    return None


def overshoots_after(
    data: SurveySetpoint, band: Band, started: Duration
) -> tuple[Overshoot, ...]:
    """Every reading over the top of the band once the clock is running."""
    found: list[Overshoot] = []
    for scan in data.scans_after(started):
        for key, value in scan.values:
            if value.degf > band.upper.degf + 1e-9:
                found.append(Overshoot(scan.elapsed, key, value, band.excursion(value)))
    return tuple(found)


def recovered_within(
    data: SurveySetpoint,
    band: Band,
    overshoots: tuple[Overshoot, ...],
    window: Duration,
) -> bool:
    """Whether every overshoot was back inside the band inside the window."""
    if not overshoots:
        return True
    for overshoot in overshoots:
        deadline = overshoot.elapsed + window
        later = [
            s
            for s in data.scans
            if overshoot.elapsed.seconds < s.elapsed.seconds <= deadline.seconds
        ]
        if not later:
            return False
        if not any(_all_inside(scan, band) for scan in later):
            return False
    return True


def _all_inside(scan: Scan, band: Band) -> bool:
    return all(band.contains(value) for _, value in scan.values)


def analyse(
    data: SurveySetpoint,
    tolerance: TemperatureDelta,
    *,
    policy: OvershootPolicy = OvershootPolicy.STRICT,
    recovery: Duration = DEFAULT_RECOVERY,
) -> Stabilization:
    """Work out when the clock started and what happened afterwards."""
    if tolerance.degf <= 0:
        raise ValidationError("tolerance must be positive", field="tolerance")
    band = band_for(data.setpoint, tolerance)
    arrival = first_arrival(data, band)
    if arrival is None:
        return Stabilization(None, None, (), True, Duration(0.0))
    started, sensor = arrival
    overshoots = overshoots_after(data, band, started)
    recovered = (
        recovered_within(data, band, overshoots, recovery)
        if policy.allows_recovery
        else not overshoots
    )
    soak = data.duration - started
    return Stabilization(started, sensor, overshoots, recovered, soak)
